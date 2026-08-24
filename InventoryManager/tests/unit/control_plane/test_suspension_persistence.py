from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.jobs import (
    ControlOutboxService,
    OutboxDispatchPermit,
    OutboxLane,
)
from inventory_control.lifecycle import (
    SuspensionActionDirection,
    SuspensionEffectKind,
    SuspensionBarrierCommand,
    SuspensionPersistenceAuthorityError,
    SuspensionPersistenceBoundaryError,
    SuspensionPersistenceConflictError,
    SuspensionPersistenceGateError,
    SuspensionPersistenceProofError,
    SuspensionPersistenceTransactionError,
    SuspensionPhase,
    SuspensionPlatformActionRequest,
    TenantSuspensionPersistenceCoordinator,
)
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.identity import (
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.models.jobs import ControlOutboxEvent
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
)
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.models.subscriptions import PlanRevision, Subscription
from inventory_control.models.suspensions import (
    TenantSuspension,
    TenantSuspensionAction,
)
from inventory_control.lifecycle.suspension_persistence import (
    _read_database_utc_now,
)


NOW = datetime(2026, 8, 22, 12, 0, 0, 654321, tzinfo=timezone.utc)
MFA_AT = datetime(2026, 8, 22, 11, 58, 0, 123456, tzinfo=timezone.utc)
RUN_ID = UUID("19000000-0000-4000-8000-000000000001")
HOLD_ID = UUID("19000000-0000-4000-8000-000000000002")
TENANT_ID = UUID("19000000-0000-4000-8000-000000000003")
DATABASE_ID = UUID("19000000-0000-4000-8000-000000000004")
ADMIN_ID = UUID("19000000-0000-4000-8000-000000000005")
TOTP_ID = UUID("19000000-0000-4000-8000-000000000006")
PLATFORM_SESSION_ID = UUID("19000000-0000-4000-8000-000000000007")
PLAN_ID = UUID("19000000-0000-4000-8000-000000000008")
SUBSCRIPTION_ID = UUID("19000000-0000-4000-8000-000000000009")
USER_ID = UUID("19000000-0000-4000-8000-00000000000a")
MEMBERSHIP_ID = UUID("19000000-0000-4000-8000-00000000000b")
USER_SESSION_ID = UUID("19000000-0000-4000-8000-00000000000c")
SUSPENSION_ID = UUID("19000000-0000-4000-8000-00000000000d")
FREEZE_ACTION_ID = UUID("19000000-0000-4000-8000-00000000000e")
RESOLVE_ACTION_ID = UUID("19000000-0000-4000-8000-00000000000f")


@pytest.mark.parametrize(
    ("dialect_name", "expected_sql"),
    (
        ("mysql", "SELECT UTC_TIMESTAMP(6)"),
        ("mariadb", "SELECT UTC_TIMESTAMP(6)"),
    ),
)
def test_default_database_clock_keeps_microseconds_and_is_dialect_safe(
    dialect_name,
    expected_sql,
):
    session = Mock()
    session.get_bind.return_value.dialect.name = dialect_name
    session.scalar.return_value = NOW.replace(tzinfo=None)

    assert _read_database_utc_now(session) == NOW
    statement = session.scalar.call_args.args[0]
    assert str(statement) == expected_sql


OUTBOX_RESULT_MAC_KEY = b"suspension-test-result-mac-key-v1!!"
FREEZE_RESULT_SAFE_CODE = "SUSPENSION_EFFECT_COMPLETED"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _seed(control_database, *, hold_state="held", mfa_at=MFA_AT):
    with control_database.transaction() as session:
        session.add(
            DisasterRecoveryRun(
                id=str(RUN_ID),
                kind="host_restore",
                policy_version=1,
                status="completed",
                expected_survivor_count=1,
                actual_survivor_count=1,
                sealed_coverage_digest=b"s" * 32,
                final_coverage_digest=b"f" * 32,
                accepted_smoke_evidence_uuid=("19000000-0000-4000-8000-000000000010"),
                host_installation_fingerprint="a" * 64,
                deployment_marker_fingerprint="b" * 64,
                row_version=2,
                started_at=NOW - timedelta(hours=2),
                reviewing_at=NOW - timedelta(hours=1),
                completed_at=NOW - timedelta(minutes=30),
                created_at=NOW - timedelta(hours=2),
                updated_at=NOW,
            )
        )
        session.add(
            Tenant(
                id=str(TENANT_ID),
                name="Test tenant",
                slug="suspension-test",
                status="active",
                access_version=7,
                row_version=3,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                database_instance_key="test-instance",
                database_name="tenant_19",
                status="ready",
                schema_version="head",
                activated_by_registration_commit_uuid=(
                    "19000000-0000-4000-8000-000000000011"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_19_dml_g7",
                dml_credential_generation=7,
                dml_root_key_version=2,
                dml_derivation_version=1,
                route_version=9,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=5,
                platform_read_username="tenant_19_read_g3",
                platform_read_credential_generation=3,
                platform_read_root_key_version=2,
                platform_read_derivation_version=1,
                platform_read_route_version=3,
                row_version=4,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            TenantRecoveryHold(
                id=str(HOLD_ID),
                recovery_run_id=str(RUN_ID),
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                state=hold_state,
                hold_revision=2,
                snapshot_underlying_status="active",
                snapshot_access_version=7,
                expected_dml_login_state_version=5,
                dml_convergence_status="active",
                held_at=NOW - timedelta(hours=1),
                released_at=NOW if hold_state == "released" else None,
                row_version=2,
                created_at=NOW - timedelta(hours=1),
                updated_at=NOW,
            )
        )
        entitlements = {"features": {}, "limits": {"member_seats": 10}}
        digest = b"e" * 32
        session.add(
            PlanRevision(
                id=str(PLAN_ID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=entitlements,
                entitlements_digest=digest,
                active=True,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            Subscription(
                id=str(SUBSCRIPTION_ID),
                tenant_id=str(TENANT_ID),
                plan_revision_uuid=str(PLAN_ID),
                entitlements_schema_version=1,
                entitlements_json=entitlements,
                entitlements_digest=digest,
                status="active",
                expires_at=NOW + timedelta(days=10),
                row_version=1,
                provider="manual",
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            PlatformAdmin(
                id=str(ADMIN_ID),
                username_canonical="suspension.admin",
                status="active",
                password_hash_encoded="$argon2id$redacted",
                password_hash_algorithm="argon2id",
                password_hash_version=1,
                auth_version=3,
                setup_version=2,
                totp_generation=1,
                recovery_code_generation=1,
                row_version=1,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            PlatformAdminTotpCredential(
                id=str(TOTP_ID),
                platform_admin_id=str(ADMIN_ID),
                generation=1,
                secret_revision=1,
                status="confirmed",
                seed_nonce=b"n" * 12,
                seed_ciphertext=b"c" * 32,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                last_accepted_time_step=42,
                row_version=1,
                created_at=NOW - timedelta(days=1),
                confirmed_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            PlatformAdminSession(
                id=str(PLATFORM_SESSION_ID),
                platform_admin_id=str(ADMIN_ID),
                token_digest_sha256=b"p" * 32,
                csrf_digest_sha256=b"q" * 32,
                auth_version_at_issue=3,
                setup_version_at_issue=2,
                mfa_method="totp",
                mfa_verified_at=mfa_at,
                totp_credential_id=str(TOTP_ID),
                totp_time_step=42,
                recovery_code_id=None,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=1800,
                created_at=mfa_at,
                last_seen_at=mfa_at,
                idle_expires_at=NOW + timedelta(minutes=20),
                absolute_expires_at=NOW + timedelta(hours=2),
            )
        )
        session.add(
            User(
                id=str(USER_ID),
                phone_region_iso2="CN",
                phone_e164="+8613800138019",
                phone_normalization_version=1,
                phone_metadata_version="test-v1",
                phone_verified_at=NOW - timedelta(days=1),
                status="active",
                auth_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW,
            )
        )
        session.add(
            TenantMembership(
                id=str(MEMBERSHIP_ID),
                tenant_id=str(TENANT_ID),
                user_id=str(USER_ID),
                role_key="admin",
                status="active",
                source_type="migration",
                row_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW,
            )
        )
        session.add(
            TenantUserSession(
                id=str(USER_SESSION_ID),
                user_id=str(USER_ID),
                token_digest_sha256=b"u" * 32,
                csrf_digest_sha256=b"v" * 32,
                auth_version_at_issue=1,
                tenant_access_version_at_issue=7,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=1800,
                created_at=NOW - timedelta(minutes=10),
                last_seen_at=NOW - timedelta(minutes=5),
                idle_expires_at=NOW + timedelta(minutes=20),
                absolute_expires_at=NOW + timedelta(hours=2),
            )
        )


def _service(session, *, now=NOW):
    return TenantSuspensionPersistenceCoordinator(
        session,
        recent_step_up_window=timedelta(minutes=10),
        outbox_result_mac_key=OUTBOX_RESULT_MAC_KEY,
        database_clock=lambda _: now,
    )


def _freeze_request(**changes):
    request = SuspensionPlatformActionRequest(
        tenant_uuid=TENANT_ID,
        suspension_uuid=SUSPENSION_ID,
        action_uuid=FREEZE_ACTION_ID,
        expected_recovery_run_uuid=RUN_ID,
        expected_hold_uuid=HOLD_ID,
        expected_hold_revision=2,
        expected_suspension_row_version=0,
        expected_barrier_generation=0,
        expected_tenant_row_version=3,
        expected_access_version=7,
        expected_route_row_version=4,
        expected_login_state_version=5,
        platform_admin_uuid=ADMIN_ID,
        platform_session_uuid=PLATFORM_SESSION_ID,
        recent_step_up_method="totp",
        recent_step_up_at=MFA_AT,
        reason_code="security_incident",
        safe_note="manual security containment",
        safe_correlation="INC-2026-0019",
        idempotency_key="freeze-tenant-19",
    )
    return replace(request, **changes)


def _complete_freeze_effect_receipts(session) -> None:
    service = ControlOutboxService()
    events = session.scalars(
        sa.select(ControlOutboxEvent).where(
            ControlOutboxEvent.source_uuid == str(FREEZE_ACTION_ID),
            ControlOutboxEvent.event_type.like("suspension.%"),
            ~ControlOutboxEvent.event_type.like("suspension.failure.%"),
        )
    ).all()
    assert len(events) == 6
    for event in events:
        event.execution_generation = 1
        permit = OutboxDispatchPermit(
            event_id=event.id,
            lane=OutboxLane.ORDINARY,
            source_type=event.source_type,
            source_uuid=event.source_uuid,
            source_generation=event.source_generation,
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            execution_generation=event.execution_generation,
            payload=event.payload,
        )
        facts_digest = hashlib.sha256(
            json.dumps(
                event.payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).digest()
        evidence = service.make_safe_result_evidence(
            permit,
            safe_code=FREEZE_RESULT_SAFE_CODE,
            safe_facts_digest=facts_digest,
            result_mac_key=OUTBOX_RESULT_MAC_KEY,
        )
        event.state = "succeeded"
        event.attempts = 1
        event.last_attempt_at = NOW
        event.completed_at = NOW
        event.updated_at = NOW
        event.result_digest_version = evidence.digest_version
        event.result_digest = evidence.digest_hex
        event.result_mac = evidence.mac_hex


def _freeze_command(**changes):
    command = SuspensionBarrierCommand(
        tenant_uuid=TENANT_ID,
        suspension_uuid=SUSPENSION_ID,
        action_uuid=FREEZE_ACTION_ID,
        expected_recovery_run_uuid=RUN_ID,
        expected_hold_uuid=HOLD_ID,
        expected_hold_revision=2,
        expected_suspension_row_version=1,
        expected_tenant_row_version=4,
        expected_access_version=8,
        expected_route_row_version=5,
        expected_login_state_version=6,
    )
    return replace(command, **changes)


def _resolve_request(**changes):
    request = SuspensionPlatformActionRequest(
        tenant_uuid=TENANT_ID,
        suspension_uuid=SUSPENSION_ID,
        action_uuid=RESOLVE_ACTION_ID,
        expected_recovery_run_uuid=RUN_ID,
        expected_hold_uuid=HOLD_ID,
        expected_hold_revision=2,
        expected_suspension_row_version=2,
        expected_barrier_generation=1,
        expected_tenant_row_version=5,
        expected_access_version=8,
        expected_route_row_version=6,
        expected_login_state_version=6,
        platform_admin_uuid=ADMIN_ID,
        platform_session_uuid=PLATFORM_SESSION_ID,
        recent_step_up_method="totp",
        recent_step_up_at=MFA_AT,
        reason_code="security_review_complete",
        safe_note="approved to begin locked candidate validation",
        safe_correlation="INC-2026-0019",
        idempotency_key="resolve-tenant-19",
    )
    return replace(request, **changes)


def _complete_freeze(control_database):
    with control_database.transaction() as session:
        _service(session).request_freeze(_freeze_request())
    with control_database.transaction() as session:
        _complete_freeze_effect_receipts(session)
    with control_database.transaction() as session:
        return _service(session).complete_freeze(_freeze_command())


def _release_hold(control_database):
    with control_database.transaction() as session:
        hold = session.get(TenantRecoveryHold, str(HOLD_ID))
        hold.state = "released"
        hold.released_at = NOW
        hold.updated_at = NOW


def _seed_deletion(control_database):
    with control_database.transaction() as session:
        session.add(
            TenantDeletionRequest(
                id="19000000-0000-4000-8000-000000000012",
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                requested_by_user_id=str(USER_ID),
                request_challenge_id=("19000000-0000-4000-8000-000000000013"),
                status="pending_review",
                request_revision=1,
                execution_generation=1,
                executor_fencing_token=1,
                current_action_id=("19000000-0000-4000-8000-000000000014"),
                committed_tenant_access_version=7,
                desired_dml_login_state="locked",
                published_dml_generation=7,
                latest_dml_generation=7,
                recovery_dispositions_required=False,
                row_version=1,
                requested_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def test_requires_an_explicit_clean_caller_transaction(control_database):
    _seed(control_database)
    with control_database.new_session() as session:
        with pytest.raises(SuspensionPersistenceTransactionError):
            _service(session).request_freeze(_freeze_request())
        session.scalar(sa.select(Tenant.id))
        with pytest.raises(SuspensionPersistenceTransactionError):
            _service(session).request_freeze(_freeze_request())

    with control_database.new_session() as session:
        transaction = session.begin()
        try:
            session.add(Tenant(id=str(UUID(int=99)), status="active"))
            with pytest.raises(SuspensionPersistenceTransactionError):
                _service(session).request_freeze(_freeze_request())
        finally:
            transaction.rollback()


def test_freeze_is_atomic_immediate_deny_with_provenance_and_outbox(
    control_database,
):
    _seed(control_database, hold_state="held")
    with control_database.transaction() as session:
        result = _service(session).request_freeze(_freeze_request())
        assert result.phase is SuspensionPhase.FREEZING
        assert result.tenant_access_version == 8
        assert result.login_state_version == 6
        assert set(result.effects) == {
            SuspensionEffectKind.REVOKE_ALL_SESSIONS,
            SuspensionEffectKind.DISPOSE_TENANT_ENGINES,
            SuspensionEffectKind.BLOCK_JOB_LEASES,
            SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
            SuspensionEffectKind.LOCK_ALL_DML_IDENTITIES,
        }

        tenant = session.get(Tenant, str(TENANT_ID), populate_existing=True)
        route = session.get(TenantDatabase, str(TENANT_ID), populate_existing=True)
        suspension = session.get(TenantSuspension, str(SUSPENSION_ID))
        action = session.get(TenantSuspensionAction, str(FREEZE_ACTION_ID))
        user_session = session.get(TenantUserSession, str(USER_SESSION_ID))
        events = session.scalars(
            sa.select(ControlOutboxEvent).where(
                ControlOutboxEvent.source_uuid == str(FREEZE_ACTION_ID)
            )
        ).all()
        assert (tenant.status, tenant.access_version, tenant.row_version) == (
            "suspending",
            8,
            4,
        )
        assert (
            route.dml_desired_login_state,
            route.dml_observed_login_state,
            route.dml_login_state_version,
            route.row_version,
        ) == ("locked", "active", 6, 5)
        assert route.dml_desired_state_recovery_run_id == str(RUN_ID)
        assert suspension.committed_tenant_row_version == 4
        assert suspension.committed_access_version == 8
        assert action.actor_type == "platform_admin"
        assert action.authorization_source == "user_step_up"
        assert action.platform_admin_id == str(ADMIN_ID)
        assert action.platform_session_id == str(PLATFORM_SESSION_ID)
        assert action.recent_step_up_at.microsecond == MFA_AT.microsecond
        assert len(action.request_digest) == 32
        assert user_session.revoked_reason_code == "tenant_suspension_barrier"
        assert len(events) == 6
        assert all(event.state == "pending" for event in events)
        assert all(
            event.payload["expected_login_state_version"] == 6
            and event.payload["recovery_run_uuid"] == str(RUN_ID)
            for event in events
        )


def test_exact_freeze_replay_does_not_duplicate_action_or_outbox(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        first = _service(session).request_freeze(_freeze_request())
    # A later overlay revision must not turn a committed exact replay into a
    # second authorization attempt or duplicate its durable effects.
    with control_database.transaction() as session:
        hold = session.get(TenantRecoveryHold, str(HOLD_ID))
        hold.hold_revision = 3
        hold.row_version += 1
    with control_database.transaction() as session:
        replay = _service(session).request_freeze(_freeze_request())
        assert replay.replayed
        assert replay.action_uuid == first.action_uuid
        assert session.scalar(sa.select(sa.func.count(TenantSuspension.id))) == 1
        assert session.scalar(sa.select(sa.func.count(TenantSuspensionAction.id))) == 1
        assert session.scalar(sa.select(sa.func.count(ControlOutboxEvent.id))) == 6

    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceConflictError) as caught:
            _service(session).request_freeze(
                _freeze_request(reason_code="different_reason")
            )
        assert caught.value.code in {
            "SUSPENSION_ACTION_REPLAY_MISMATCH",
            "SUSPENSION_IDEMPOTENCY_CONFLICT",
        }


def test_outer_rollback_removes_claim_action_projection_and_events(
    control_database,
):
    _seed(control_database)
    with control_database.new_session() as session:
        transaction = session.begin()
        _service(session).request_freeze(_freeze_request())
        transaction.rollback()

    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_ID))
        route = session.get(TenantDatabase, str(TENANT_ID))
        user_session = session.get(TenantUserSession, str(USER_SESSION_ID))
        assert (tenant.status, tenant.access_version, tenant.row_version) == (
            "active",
            7,
            3,
        )
        assert (
            route.dml_desired_login_state,
            route.dml_login_state_version,
            route.row_version,
        ) == ("active", 5, 4)
        assert user_session.revoked_at is None
        assert session.get(TenantSuspension, str(SUSPENSION_ID)) is None
        assert session.get(TenantSuspensionAction, str(FREEZE_ACTION_ID)) is None
        assert session.scalar(sa.select(sa.func.count(ControlOutboxEvent.id))) == 0


def test_stale_fence_or_expired_step_up_fails_without_partial_write(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceConflictError):
            _service(session).request_freeze(
                _freeze_request(expected_login_state_version=4)
            )
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceAuthorityError):
            _service(session, now=NOW + timedelta(minutes=20)).request_freeze(
                _freeze_request()
            )
    with control_database.new_session() as session:
        assert session.get(Tenant, str(TENANT_ID)).status == "active"
        assert session.get(TenantSuspension, str(SUSPENSION_ID)) is None


def test_cas_detects_a_version_change_after_current_read(control_database):
    _seed(control_database)

    class RacingCoordinator(TenantSuspensionPersistenceCoordinator):
        def _validate_platform_authority(self, *args, **kwargs):
            super()._validate_platform_authority(*args, **kwargs)
            self._session.execute(
                sa.update(Tenant)
                .where(Tenant.id == str(TENANT_ID))
                .values(row_version=99)
                .execution_options(synchronize_session=False)
            )

    with pytest.raises(SuspensionPersistenceConflictError) as caught:
        with control_database.transaction() as session:
            RacingCoordinator(
                session,
                recent_step_up_window=timedelta(minutes=10),
                outbox_result_mac_key=OUTBOX_RESULT_MAC_KEY,
                database_clock=lambda _: NOW,
            ).request_freeze(_freeze_request())
    assert caught.value.code == "SUSPENSION_TENANT_FENCE_CONFLICT"
    with control_database.new_session() as session:
        assert session.get(Tenant, str(TENANT_ID)).row_version == 3
        assert session.get(TenantSuspension, str(SUSPENSION_ID)) is None


def test_freeze_completion_requires_authenticated_persisted_receipts_and_replays(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        _service(session).request_freeze(_freeze_request())

    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceProofError):
            _service(session).complete_freeze(_freeze_command())
    with control_database.transaction() as session:
        _complete_freeze_effect_receipts(session)
    with control_database.transaction() as session:
        completed = _service(session).complete_freeze(_freeze_command())
        assert completed.tenant_status.value == "suspended"
        assert completed.phase is SuspensionPhase.ACTIVE
        assert completed.suspension_row_version == 2
        assert completed.route_row_version == 6
        route = session.get(TenantDatabase, str(TENANT_ID), populate_existing=True)
        assert route.dml_observed_login_state == "locked"
    with control_database.transaction() as session:
        replay = _service(session).complete_freeze(_freeze_command())
        assert replay.replayed
        assert replay.suspension_row_version == 2
        assert replay.route_row_version == 6
        action = session.get(TenantSuspensionAction, str(FREEZE_ACTION_ID))
        assert action.state == "succeeded"
        assert action.row_version == 2


def test_freeze_completion_rejects_tampered_persisted_result_mac(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        _service(session).request_freeze(_freeze_request())
    with control_database.transaction() as session:
        _complete_freeze_effect_receipts(session)
        event = session.scalar(
            sa.select(ControlOutboxEvent).where(
                ControlOutboxEvent.source_uuid == str(FREEZE_ACTION_ID)
            )
        )
        event.result_mac = "0" * 64
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceProofError) as caught:
            _service(session).complete_freeze(_freeze_command())
        assert caught.value.code == "SUSPENSION_BARRIER_RECEIPT_INVALID"
    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_ID))
        route = session.get(TenantDatabase, str(TENANT_ID))
        assert tenant.status == "suspending"
        assert route.dml_observed_login_state == "active"


def test_freeze_failure_stays_denied_and_changed_failure_is_not_replay(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        _service(session).request_freeze(_freeze_request())
    with control_database.transaction() as session:
        failed = _service(session).fail_barrier(
            _freeze_command(), failure_code="account_lock_incomplete"
        )
        assert failed.phase is SuspensionPhase.FAILED
        tenant = session.get(Tenant, str(TENANT_ID), populate_existing=True)
        route = session.get(TenantDatabase, str(TENANT_ID), populate_existing=True)
        assert tenant.status == "suspending"
        assert route.dml_desired_login_state == "locked"
    with control_database.transaction() as session:
        replay = _service(session).fail_barrier(
            _freeze_command(), failure_code="account_lock_incomplete"
        )
        assert replay.replayed
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceConflictError) as caught:
            _service(session).fail_barrier(
                _freeze_command(), failure_code="different_failure"
            )
        assert caught.value.code == "SUSPENSION_FAILURE_REPLAY_MISMATCH"
    with control_database.transaction() as session:
        _complete_freeze_effect_receipts(session)
    with control_database.transaction() as session:
        recovered = _service(session).complete_freeze(
            _freeze_command(expected_suspension_row_version=2),
        )
        assert recovered.phase is SuspensionPhase.ACTIVE
        assert recovered.suspension_row_version == 3


def test_resolve_requires_released_hold_and_no_deletion(control_database):
    _seed(control_database)
    _complete_freeze(control_database)
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceGateError) as caught:
            _service(session).request_resolve(_resolve_request())
        assert caught.value.code == "SUSPENSION_RECOVERY_HOLD_NOT_RELEASED"

    _release_hold(control_database)
    _seed_deletion(control_database)
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceGateError) as caught:
            _service(session).request_resolve(_resolve_request())
        assert caught.value.code == "SUSPENSION_DELETION_IN_PROGRESS"


def test_resolve_intent_stays_locked_unpublished_and_exactly_replays(
    control_database,
):
    _seed(control_database)
    _complete_freeze(control_database)
    _release_hold(control_database)
    with control_database.transaction() as session:
        result = _service(session).request_resolve(_resolve_request())
        assert result.phase is SuspensionPhase.RESOLVING
        assert result.candidate_dml_generation == 8
        assert result.tenant_access_version == 9
        tenant = session.get(Tenant, str(TENANT_ID), populate_existing=True)
        route = session.get(TenantDatabase, str(TENANT_ID), populate_existing=True)
        action = session.get(TenantSuspensionAction, str(RESOLVE_ACTION_ID))
        candidate_event = session.scalar(
            sa.select(ControlOutboxEvent).where(
                ControlOutboxEvent.source_uuid == str(RESOLVE_ACTION_ID),
                ControlOutboxEvent.event_type
                == "suspension.create_locked_unpublished_dml_candidate",
            )
        )
        assert (tenant.status, tenant.access_version) == ("resuming", 9)
        assert (
            route.dml_username,
            route.dml_credential_generation,
            route.dml_desired_login_state,
            route.dml_observed_login_state,
            route.route_version,
            route.row_version,
        ) == (
            "tenant_19_dml_g7",
            7,
            "locked",
            "locked",
            9,
            6,
        )
        assert action.generation == 2
        assert candidate_event.payload["dml_generation"] == 8

    with control_database.transaction() as session:
        replay = _service(session).request_resolve(_resolve_request())
        assert replay.replayed
        assert replay.candidate_dml_generation == 8
        assert (
            session.scalar(
                sa.select(sa.func.count(TenantSuspensionAction.id)).where(
                    TenantSuspensionAction.suspension_id == str(SUSPENSION_ID)
                )
            )
            == 2
        )
        assert (
            session.scalar(
                sa.select(sa.func.count(ControlOutboxEvent.id)).where(
                    ControlOutboxEvent.source_uuid == str(RESOLVE_ACTION_ID)
                )
            )
            == 5
        )


def test_locking_selects_follow_global_order(control_database):
    _seed(control_database)
    _complete_freeze(control_database)
    _release_hold(control_database)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    sa.event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:
            _service(session).request_resolve(_resolve_request())
    finally:
        sa.event.remove(control_database.engine, "before_cursor_execute", capture)

    tables = (
        "tenants",
        "disaster_recovery_runs",
        "tenant_recovery_holds",
        "tenant_deletion_requests",
        "tenant_suspensions",
        "tenant_suspension_actions",
        "subscriptions",
        "tenant_databases",
    )
    positions = []
    for table in tables:
        positions.append(
            next(index for index, sql in enumerate(statements) if table in sql)
        )
    assert positions == sorted(positions)


def test_physical_resume_and_enforce_locked_boundaries_fail_closed(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceBoundaryError) as resume:
            _service(session).complete_resume()
        assert resume.value.code == "SUSPENSION_ACCOUNT_MUTATION_PROOF_REQUIRED"
    with control_database.transaction() as session:
        with pytest.raises(SuspensionPersistenceBoundaryError) as enforce:
            _service(session).request_enforce_locked()
        assert enforce.value.code == "SUSPENSION_ENFORCE_LOCKED_REDUCER_REQUIRED"


def test_suspension_tables_store_no_password_ciphertext_or_dsn_columns():
    column_names = {
        column.name.lower()
        for table in (
            TenantSuspension.__table__,
            TenantSuspensionAction.__table__,
        )
        for column in table.columns
    }
    for forbidden in (
        "password",
        "hash",
        "ciphertext",
        "secret",
        "dsn",
        "connection_url",
    ):
        assert not any(forbidden in name for name in column_names)
