from datetime import datetime, timedelta, timezone

import hashlib
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from inventory_control import (
    ControlBase,
    Tenant,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateDecision,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    CsrfAuthenticationError,
    PHONE_NORMALIZATION_VERSION,
    SessionAuthenticationError,
    SessionIssueError,
    SessionService,
    SessionTargetNotFound,
    issue_csrf_token,
    issue_session_token,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def control_database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def control_database(control_database_schema):
    clear_guarded_mysql_test_rows(
        control_database_schema.engine,
        ControlBase.metadata,
    )
    return control_database_schema


@pytest.fixture
def identity_ids(control_database):
    with control_database.transaction() as session:
        tenant = Tenant(status="active", access_version=7)
        user = User(
            phone_e164="+8613800138000",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=NOW,
            status="active",
        )
        session.add_all([tenant, user])
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role_key="admin",
            status="active",
            source_type="migration",
        )
        session.add(membership)
        session.flush()
        return tenant.id, user.id, membership.id


def _issue(service, session, user_id, *, now=NOW):
    return service.issue(
        session,
        user_id=user_id,
        idle_timeout=timedelta(minutes=30),
        absolute_timeout=timedelta(hours=8),
        policy_version=1,
        device_name="Office browser",
        user_agent_summary="desktop/chromium",
        ip_summary="private-network",
        now=now,
    )


def _gate_reader(_session, tenant, _now):
    gates = {
        "active": EffectiveTenantGate.ACTIVE,
        "expired": EffectiveTenantGate.EXPIRED,
        "suspended": EffectiveTenantGate.SUSPENDED,
    }
    gate = gates.get(tenant.status, EffectiveTenantGate.RECOVERY_HOLD)
    return TenantGateDecision(
        gate=gate,
        error_code=None if gate is EffectiveTenantGate.ACTIVE else gate.value,
    )


def _service(gate_reader=_gate_reader):
    return SessionService(gate_current_read=gate_reader)


def _decision(gate):
    return TenantGateDecision(
        gate=gate,
        error_code=None if gate is EffectiveTenantGate.ACTIVE else gate.value,
    )


def test_session_digest_collision_is_discarded_and_retried(
    control_database,
    identity_ids,
) -> None:
    _, user_id, _ = identity_ids
    colliding_bearer = issue_session_token()
    fresh_bearer = issue_session_token()
    csrf_values = [
        issue_csrf_token(),
        issue_csrf_token(),
        issue_csrf_token(),
    ]
    bearer_values = iter(
        [colliding_bearer, colliding_bearer, fresh_bearer]
    )
    csrf_iterator = iter(csrf_values)
    service = SessionService(
        gate_current_read=_gate_reader,
        session_token_issuer=lambda: next(bearer_values),
        csrf_token_issuer=lambda: next(csrf_iterator),
    )

    with control_database.transaction() as session:
        first = _issue(service, session, user_id)
    with control_database.transaction() as session:
        second = _issue(
            service,
            session,
            user_id,
            now=NOW + timedelta(seconds=1),
        )

    assert first.session_token == colliding_bearer.plaintext
    assert second.session_token == fresh_bearer.plaintext
    with control_database.new_session() as session:
        assert session.scalar(select(func.count(TenantUserSession.id))) == 2


def test_issue_persists_only_digests_and_resolve_returns_safe_dto(
    control_database, identity_ids
):
    tenant_id, user_id, membership_id = identity_ids
    service = _service()
    with control_database.transaction() as session:
        issued = _issue(service, session, user_id)
        session_id = issued.auth.session_id
        assert issued.auth.tenant_id == tenant_id
        assert issued.auth.membership_id == membership_id
        assert issued.auth.role is TenantRole.ADMIN
        assert issued.session_token not in repr(issued)
        assert issued.csrf_token not in repr(issued)

    with control_database.new_session() as session:
        row = session.get(TenantUserSession, session_id)
        assert row.token_digest_sha256 == hashlib.sha256(
            issued.session_token.encode("ascii")
        ).digest()
        assert row.csrf_digest_sha256 == hashlib.sha256(
            issued.csrf_token.encode("ascii")
        ).digest()
        assert "session_token" not in row.__table__.columns
        assert "csrf_token" not in row.__table__.columns

    with control_database.transaction() as session:
        resolved = service.resolve(
            session,
            issued.session_token,
            now=NOW + timedelta(minutes=10),
            ip_summary="private-network-2",
        )
        assert resolved.session_id == session_id
        assert resolved.role is TenantRole.ADMIN
        assert not hasattr(resolved, "session_token")
        assert not hasattr(resolved, "csrf_token")
        assert resolved.idle_expires_at.replace(tzinfo=timezone.utc) == (
            NOW + timedelta(minutes=40)
        )


@pytest.mark.parametrize(
    "gate",
    [
        EffectiveTenantGate.ACTIVE,
        EffectiveTenantGate.EXPIRED,
        EffectiveTenantGate.SUSPENDED,
    ],
)
def test_issue_returns_the_current_authenticated_surface_gate(
    control_database, identity_ids, gate
):
    _, user_id, _ = identity_ids
    service = _service(lambda _session, _tenant, _now: _decision(gate))

    with control_database.transaction() as session:
        issued = _issue(service, session, user_id)

    assert issued.auth.effective_gate is gate


@pytest.mark.parametrize(
    "gate",
    [
        EffectiveTenantGate.RECOVERY_HOLD,
        EffectiveTenantGate.DELETION_COOLING_OFF,
        EffectiveTenantGate.DELETED,
        EffectiveTenantGate.PROVISIONING,
        EffectiveTenantGate.STALE_ACCESS,
        EffectiveTenantGate.INVALID_STATE,
    ],
)
def test_issue_fails_closed_before_persisting_for_non_session_gates(
    control_database, identity_ids, gate
):
    _, user_id, _ = identity_ids
    service = _service(lambda _session, _tenant, _now: _decision(gate))

    with control_database.transaction() as session:
        with pytest.raises(SessionIssueError):
            _issue(service, session, user_id)
        assert session.scalar(select(TenantUserSession.id)) is None


def test_resolve_reduces_the_current_gate_without_rotating_an_existing_session(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    state = {"gate": EffectiveTenantGate.ACTIVE}
    service = _service(
        lambda _session, _tenant, _now: _decision(state["gate"])
    )
    with control_database.transaction() as session:
        issued = _issue(service, session, user_id)

    state["gate"] = EffectiveTenantGate.EXPIRED
    with control_database.transaction() as session:
        resolved = service.resolve(
            session,
            issued.session_token,
            now=NOW + timedelta(minutes=1),
        )
        assert resolved.session_id == issued.auth.session_id
        assert resolved.effective_gate is EffectiveTenantGate.EXPIRED

    state["gate"] = EffectiveTenantGate.RECOVERY_HOLD
    with control_database.new_session() as session:
        with pytest.raises(SessionAuthenticationError):
            service.resolve(
                session,
                issued.session_token,
                now=NOW + timedelta(minutes=2),
            )


def test_gate_reader_errors_and_malformed_results_fail_closed(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids

    for invalid_reader in (
        lambda _session, _tenant, _now: None,
        lambda _session, _tenant, _now: (_ for _ in ()).throw(
            RuntimeError("unavailable")
        ),
    ):
        service = _service(invalid_reader)
        with control_database.transaction() as session:
            with pytest.raises(SessionIssueError):
                _issue(service, session, user_id)
            assert session.scalar(select(TenantUserSession.id)) is None


def test_csrf_is_current_independent_and_bound_to_one_session(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    service = _service()
    with control_database.transaction() as session:
        first = _issue(service, session, user_id)
        second = _issue(service, session, user_id, now=NOW + timedelta(seconds=1))

    with control_database.transaction() as session:
        service.verify_csrf(
            session,
            auth=first.auth,
            presented_csrf=first.csrf_token,
            now=NOW + timedelta(minutes=1),
        )
        for invalid in (
            first.session_token,
            second.csrf_token,
            "malformed",
            None,
        ):
            with pytest.raises(CsrfAuthenticationError):
                service.verify_csrf(
                    session,
                    auth=first.auth,
                    presented_csrf=invalid,
                    now=NOW + timedelta(minutes=1),
                )

    with control_database.transaction() as session:
        session.get(TenantUserSession, first.auth.session_id).csrf_generation += 1

    with control_database.new_session() as session:
        with pytest.raises(CsrfAuthenticationError):
            service.verify_csrf(
                session,
                auth=first.auth,
                presented_csrf=first.csrf_token,
                now=NOW + timedelta(minutes=2),
            )


def test_csrf_reduces_a_fresh_gate_and_maps_closed_gate_to_fixed_error(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    state = {"gate": EffectiveTenantGate.ACTIVE}
    service = _service(
        lambda _session, _tenant, _now: _decision(state["gate"])
    )
    with control_database.transaction() as session:
        issued = _issue(service, session, user_id)

    state["gate"] = EffectiveTenantGate.SUSPENDED
    with control_database.transaction() as session:
        assert (
            service.verify_csrf(
                session,
                auth=issued.auth,
                presented_csrf=issued.csrf_token,
                now=NOW + timedelta(minutes=1),
            )
            is EffectiveTenantGate.SUSPENDED
        )

    state["gate"] = EffectiveTenantGate.DELETION_COOLING_OFF
    with control_database.new_session() as session:
        with pytest.raises(CsrfAuthenticationError):
            service.verify_csrf(
                session,
                auth=issued.auth,
                presented_csrf=issued.csrf_token,
                now=NOW + timedelta(minutes=2),
            )


@pytest.mark.parametrize("stale_fact", ["user", "tenant", "membership"])
def test_resolve_rejects_stale_identity_facts(
    control_database, identity_ids, stale_fact
):
    tenant_id, user_id, _ = identity_ids
    service = _service()
    with control_database.transaction() as session:
        issued = _issue(service, session, user_id)

    with control_database.transaction() as session:
        if stale_fact == "user":
            session.get(User, user_id).auth_version += 1
        elif stale_fact == "tenant":
            session.get(Tenant, tenant_id).access_version += 1
        else:
            membership = session.scalar(
                select(TenantMembership).where(TenantMembership.user_id == user_id)
            )
            membership.status = "disabled"

    with control_database.new_session() as session:
        with pytest.raises(SessionAuthenticationError):
            service.resolve(session, issued.session_token, now=NOW + timedelta(minutes=1))


def test_resolve_rejects_missing_malformed_and_expired_tokens(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    service = _service()
    with control_database.transaction() as session:
        issued = service.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=5),
            absolute_timeout=timedelta(hours=1),
            now=NOW,
        )

    with control_database.new_session() as session:
        for token in ("malformed", None):
            with pytest.raises(SessionAuthenticationError) as caught:
                service.resolve(session, token, now=NOW + timedelta(minutes=1))
            assert issued.session_token not in str(caught.value)
        with pytest.raises(SessionAuthenticationError):
            service.resolve(
                session,
                issued.session_token,
                now=NOW + timedelta(minutes=5),
            )


def test_revoke_one_is_owner_scoped_and_immediate(control_database, identity_ids):
    _, user_id, _ = identity_ids
    service = _service()
    with control_database.transaction() as session:
        actor = _issue(service, session, user_id)
        target = _issue(service, session, user_id, now=NOW + timedelta(seconds=1))

    with control_database.transaction() as session:
        changed = service.revoke_one(
            session,
            user_id=user_id,
            target_session_id=target.auth.session_id,
            reason_code="user_revoked_device",
            revoked_by_session_id=actor.auth.session_id,
            now=NOW + timedelta(minutes=1),
        )
        assert changed is True

    with control_database.new_session() as session:
        with pytest.raises(SessionAuthenticationError):
            service.resolve(session, target.session_token, now=NOW + timedelta(minutes=2))
        assert (
            service.resolve(
                session, actor.session_token, now=NOW + timedelta(minutes=2)
            ).session_id
            == actor.auth.session_id
        )
        with pytest.raises(SessionTargetNotFound):
            service.revoke_one(
                session,
                user_id="00000000-0000-0000-0000-000000000999",
                target_session_id=actor.auth.session_id,
                reason_code="cross_user_attempt",
                now=NOW + timedelta(minutes=2),
            )


def test_revoke_all_advances_auth_version_and_revokes_every_session(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    service = _service()
    with control_database.transaction() as session:
        first = _issue(service, session, user_id)
        second = _issue(service, session, user_id, now=NOW + timedelta(seconds=1))

    with control_database.transaction() as session:
        result = service.revoke_all(
            session,
            user_id=user_id,
            reason_code="user_revoked_all",
            revoked_by_session_id=first.auth.session_id,
            now=NOW + timedelta(minutes=1),
        )
        assert result.revoked_count == 2
        assert result.new_auth_version == 2

    with control_database.new_session() as session:
        assert session.get(User, user_id).auth_version == 2
        for token in (first.session_token, second.session_token):
            with pytest.raises(SessionAuthenticationError):
                service.resolve(session, token, now=NOW + timedelta(minutes=2))


def test_database_allows_only_one_unreleased_membership_per_user(
    control_database, identity_ids
):
    _, user_id, _ = identity_ids
    with control_database.transaction() as session:
        second_tenant = Tenant(status="active")
        session.add(second_tenant)
        session.flush()
        duplicate = TenantMembership(
            tenant_id=second_tenant.id,
            user_id=user_id,
            role_key="operator",
            source_type="invitation",
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()

    with control_database.transaction() as session:
        current = session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user_id)
        )
        current.status = "released"
        current.released_at = NOW
        second_tenant = Tenant(status="active")
        session.add(second_tenant)
        session.flush()
        replacement = TenantMembership(
            tenant_id=second_tenant.id,
            user_id=user_id,
            role_key="operator",
            source_type="invitation",
        )
        session.add(replacement)
        session.flush()
        assert replacement.claimed_user_id == user_id
