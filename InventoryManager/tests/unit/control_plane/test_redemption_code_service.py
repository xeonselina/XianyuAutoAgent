from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import (
    EncryptedEnvelope,
    RootKey,
    RootKeyLifecycle,
    RootKeyRing,
)
from inventory_control.models import (
    PlanRevision,
    PlatformAdmin,
    RedemptionCode,
    RedemptionCodeBatch,
)
from inventory_control.redemption import (
    RedemptionBatchConflictError,
    RedemptionCodeManagementService,
    RedemptionCodeRevisionConflict,
    RedemptionCodeSecretContext,
    RedemptionCodeService,
    RedemptionGenerationDenied,
    decrypt_redemption_code,
)
from inventory_control.subscriptions import parse_core_entitlements


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
RUN_UUID = UUID("10000000-0000-4000-8000-000000000001")
PLAN_UUID = UUID("10000000-0000-4000-8000-000000000002")
ADMIN_UUID = UUID("10000000-0000-4000-8000-000000000003")
REQUEST_UUID = UUID("10000000-0000-4000-8000-000000000004")
ROOT_KEY = RootKey(version=3, material=b"r" * 32)
ROOT_KEY_RING = RootKeyRing(
    active_version=ROOT_KEY.version,
    keys={ROOT_KEY.version: ROOT_KEY},
    statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
)
ENTITLEMENTS = {
    "features": {"xianyu_sync": True},
    "limits": {"member_seats": 10},
}


@pytest.fixture
def database(mysql_control_database):
    value = mysql_control_database
    snapshot = parse_core_entitlements(schema_version=1, entitlements=ENTITLEMENTS)
    with value.transaction() as session:
        session.add(
            PlatformAdmin(
                id=str(ADMIN_UUID),
                username_canonical="platform-admin",
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
    return value


def generate(service, session, **overrides):
    values = {
        "root_key": ROOT_KEY,
        "current_recovery_run_uuid": RUN_UUID,
        "recovery_run_completed": True,
        "platform_admin_uuid": ADMIN_UUID,
        "generation_request_uuid": REQUEST_UUID,
        "plan_revision_uuid": PLAN_UUID,
        "name": "August Core codes",
        "quantity": 3,
        "service_duration": timedelta(days=30),
        "redeem_before": NOW + timedelta(days=60),
        "database_now": NOW,
    }
    values.update(overrides)
    return service.generate_batch(session, **values)


def test_generation_persists_only_hash_and_authenticated_ciphertext(database):
    service = RedemptionCodeService()
    with database.transaction() as session:
        result = generate(
            service,
            session,
            channel=" Direct_Sales ",
            internal_note=" August customer delivery. ",
        )
        plaintext_values = [issued.plaintext.value for issued in result.issued_codes]
        assert result.created
        assert len(plaintext_values) == 3
        assert len(set(plaintext_values)) == 3
        assert all(value not in repr(result) for value in plaintext_values)

    with database.new_session() as session:
        batch = session.get(RedemptionCodeBatch, str(result.batch_uuid))
        records = list(
            session.scalars(
                select(RedemptionCode).order_by(RedemptionCode.id.asc())
            )
        )
        assert batch.quantity == 3
        assert batch.channel == "direct_sales"
        assert batch.internal_note == "August customer delivery."
        assert batch.plaintext_exported_at is not None
        assert len(records) == 3
        assert len({record.lookup_hash for record in records}) == 3
        decrypted = set()
        for record in records:
            context = RedemptionCodeSecretContext(
                code_uuid=UUID(record.id),
                crypto_context_uuid=UUID(record.crypto_context_uuid),
                batch_uuid=UUID(record.batch_id),
                plan_revision_uuid=UUID(record.plan_revision_uuid),
                entitlements_schema_version=record.entitlements_schema_version,
                entitlements_digest_sha256=record.entitlements_digest,
                service_duration_seconds=record.service_duration_seconds,
                redeem_before=record.redeem_before.replace(tzinfo=timezone.utc),
                created_under_recovery_run_uuid=UUID(
                    record.created_under_recovery_run_uuid
                ),
                secret_revision=record.secret_revision,
            )
            decrypted.add(
                decrypt_redemption_code(
                    root_key=ROOT_KEY,
                    context=context,
                    envelope=EncryptedEnvelope(
                        nonce=record.code_nonce,
                        ciphertext=record.code_ciphertext,
                        root_key_version=record.root_key_version,
                        crypto_version=record.crypto_version,
                        aad_version=record.aad_version,
                    ),
                ).value
            )
    assert decrypted == set(plaintext_values)


def test_generation_retry_does_not_create_or_bulk_export_again(database):
    service = RedemptionCodeService()
    with database.transaction() as session:
        first = generate(service, session)
    with database.transaction() as session:
        retry = generate(service, session)

    assert retry.created is False
    assert retry.batch_uuid == first.batch_uuid
    assert retry.issued_codes == ()
    with database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(RedemptionCodeBatch)) == 1
        assert session.scalar(select(func.count()).select_from(RedemptionCode)) == 3


def test_generation_request_parameter_drift_is_rejected(database):
    service = RedemptionCodeService()
    with database.transaction() as session:
        generate(service, session)
    with pytest.raises(RedemptionBatchConflictError, match="changed"):
        with database.transaction() as session:
            generate(service, session, quantity=4)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"recovery_run_completed": False}, "RECOVERY_NOT_COMPLETED"),
        ({"quantity": 0}, "positive"),
        ({"service_duration": timedelta(microseconds=1)}, "whole seconds"),
        ({"redeem_before": NOW}, "later"),
        ({"channel": "contains spaces"}, "channel"),
        ({"internal_note": "   "}, "internal_note"),
    ],
)
def test_generation_fails_closed_on_invalid_authority_or_terms(
    database, overrides, expected
):
    with pytest.raises((RedemptionGenerationDenied, ValueError), match=expected):
        with database.transaction() as session:
            generate(RedemptionCodeService(), session, **overrides)


def test_preview_is_current_run_only_and_expires_at_exact_boundary(database):
    service = RedemptionCodeService()
    with database.transaction() as session:
        result = generate(
            service,
            session,
            quantity=1,
            redeem_before=NOW + timedelta(seconds=1),
        )
        lookup_hash = result.issued_codes[0].plaintext.lookup_hash

    with database.transaction() as session:
        wrong_run = service.preview_for_update(
            session,
            lookup_hash=lookup_hash,
            current_recovery_run_uuid=uuid4(),
            recovery_run_completed=True,
            database_now=NOW,
        )
        assert not wrong_run.eligible

    with database.transaction() as session:
        active = service.preview_for_update(
            session,
            lookup_hash=lookup_hash,
            current_recovery_run_uuid=RUN_UUID,
            recovery_run_completed=True,
            database_now=NOW,
        )
        assert active.eligible
        assert active.service_duration_seconds == 30 * 24 * 60 * 60

    with database.transaction() as session:
        expired = service.preview_for_update(
            session,
            lookup_hash=lookup_hash,
            current_recovery_run_uuid=RUN_UUID,
            recovery_run_completed=True,
            database_now=NOW + timedelta(seconds=1),
        )
        assert not expired.eligible
    with database.new_session() as session:
        record = session.scalar(select(RedemptionCode))
        assert record.status == "expired"
        assert record.expired_at is not None


def test_management_list_masks_plaintext_and_projects_effective_expiry(database):
    with database.transaction() as session:
        generated = generate(RedemptionCodeService(), session)

    service = RedemptionCodeManagementService()
    with database.new_session() as session:
        active = service.list_codes(
            session,
            database_now=NOW,
            page=1,
            page_size=2,
            status="active",
        )
        effective_expired = service.list_codes(
            session,
            database_now=NOW + timedelta(days=61),
            page=1,
            page_size=100,
            status="expired",
        )

    plaintexts = {item.plaintext.value for item in generated.issued_codes}
    assert active.total == 3
    assert len(active.items) == 2
    assert all(item.status == "active" for item in active.items)
    assert all(item.masked_code.endswith("****-**") for item in active.items)
    assert all(value not in repr(active) for value in plaintexts)
    assert effective_expired.total == 3
    assert {item.status for item in effective_expired.items} == {"expired"}


def test_management_reveal_uses_referenced_root_and_returns_no_secret_in_repr(
    database,
):
    with database.transaction() as session:
        generated = generate(
            RedemptionCodeService(),
            session,
            quantity=1,
        )
    issued = generated.issued_codes[0]

    with database.transaction() as session:
        revealed = RedemptionCodeManagementService().reveal_code(
            session,
            code_uuid=issued.code_uuid,
            root_key_ring=ROOT_KEY_RING,
        )

    assert revealed.plaintext == issued.plaintext
    assert issued.plaintext.value not in repr(revealed)


def test_management_revocation_is_fenced_and_exact_replay_is_idempotent(database):
    with database.transaction() as session:
        generated = generate(
            RedemptionCodeService(),
            session,
            quantity=1,
        )
    code_uuid = generated.issued_codes[0].code_uuid
    service = RedemptionCodeManagementService()

    with pytest.raises(RedemptionCodeRevisionConflict):
        with database.transaction() as session:
            service.revoke_code(
                session,
                code_uuid=code_uuid,
                expected_row_version=2,
                reason_code="operator_revoked",
                database_now=NOW,
            )

    with database.transaction() as session:
        revoked = service.revoke_code(
            session,
            code_uuid=code_uuid,
            expected_row_version=1,
            reason_code="operator_revoked",
            database_now=NOW,
        )
    with database.transaction() as session:
        replay = service.revoke_code(
            session,
            code_uuid=code_uuid,
            expected_row_version=1,
            reason_code="operator_revoked",
            database_now=NOW + timedelta(seconds=1),
        )

    assert revoked.changed is True
    assert revoked.status == "revoked"
    assert revoked.row_version == 2
    assert replay.changed is False
    assert replay.status == "revoked"
    assert replay.row_version == 2


def test_management_expired_or_reserved_code_is_not_revoked(database):
    with database.transaction() as session:
        generated = generate(
            RedemptionCodeService(),
            session,
            quantity=2,
            redeem_before=NOW + timedelta(seconds=1),
        )
        reserved = session.get(
            RedemptionCode,
            str(generated.issued_codes[1].code_uuid),
        )
        reserved.status = "reserved"
        reserved.reserved_registration_attempt_uuid = str(uuid4())
        reserved.reserved_user_uuid = str(uuid4())
    service = RedemptionCodeManagementService()

    with database.transaction() as session:
        expired = service.revoke_code(
            session,
            code_uuid=generated.issued_codes[0].code_uuid,
            expected_row_version=1,
            reason_code="operator_revoked",
            database_now=NOW + timedelta(seconds=1),
        )
        reserved_result = service.revoke_code(
            session,
            code_uuid=generated.issued_codes[1].code_uuid,
            expected_row_version=1,
            reason_code="operator_revoked",
            database_now=NOW,
        )

    assert expired.status == "expired"
    assert expired.denial_reason == "redemption_code.expired"
    assert reserved_result.status == "reserved"
    assert reserved_result.denial_reason == "redemption_code.not_revocable"
