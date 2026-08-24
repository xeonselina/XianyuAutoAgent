from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from inventory_control import (
    Tenant,
    TenantAuthSecurityEvent,
    TenantInvitation,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.models import MemberSeatGuard
from inventory_control.domain import TenantRole
from inventory_control.identity import (
    AdminPermissionChangeProof,
    CN_MOBILE_METADATA_VERSION,
    LastActiveAdminError,
    MemberSeatLimitError,
    MembershipMutationAction,
    MembershipMutationAuthorityError,
    PHONE_NORMALIZATION_VERSION,
    TenantMembershipService,
    plan_membership_mutation,
)

NOW = datetime(2026, 8, 23, 1, 45, tzinfo=timezone.utc)


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def _user(index: int, *, status: str = "active") -> User:
    return User(
        id=str(uuid4()),
        phone_e164=f"+86138{index:08d}",
        phone_normalization_version=PHONE_NORMALIZATION_VERSION,
        phone_metadata_version=CN_MOBILE_METADATA_VERSION,
        phone_verified_at=NOW,
        status=status,
        auth_version=1,
    )


def _membership(tenant_id: str, user_id: str, *, role: str, status="active"):
    return TenantMembership(
        id=str(uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        role_key=role,
        status=status,
        source_type="invitation",
    )


def _session(user_id: str, *, token_byte: int) -> TenantUserSession:
    return TenantUserSession(
        id=str(uuid4()),
        user_id=user_id,
        token_digest_sha256=bytes([token_byte]) * 32,
        csrf_digest_sha256=bytes([token_byte + 50]) * 32,
        auth_version_at_issue=1,
        tenant_access_version_at_issue=1,
        policy_version=1,
        csrf_generation=1,
        idle_timeout_seconds=3600,
        created_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(hours=8),
        device_name="test",
        user_agent_summary="test",
    )


def _seed(database, *, target_role="operator", target_status="active", admins=1):
    with database.transaction() as session:
        tenant = Tenant(id=str(uuid4()), status="active")
        session.add(tenant)
        session.flush()
        session.add(MemberSeatGuard(tenant_id=tenant.id))
        actor_user = _user(1)
        target_user = _user(2)
        session.add_all([actor_user, target_user])
        session.flush()
        actor = _membership(tenant.id, actor_user.id, role="admin")
        target = _membership(
            tenant.id,
            target_user.id,
            role=target_role,
            status=target_status,
        )
        session.add_all([actor, target])
        for index in range(1, admins):
            extra = _user(index + 10)
            session.add(extra)
            session.flush()
            session.add(_membership(tenant.id, extra.id, role="admin"))
        actor_session = _session(actor_user.id, token_byte=1)
        target_session = _session(target_user.id, token_byte=2)
        session.add_all([actor_session, target_session])
        session.flush()
        return {
            "tenant": UUID(tenant.id),
            "actor_user": UUID(actor_user.id),
            "actor_membership": UUID(actor.id),
            "actor_session": UUID(actor_session.id),
            "target_user": UUID(target_user.id),
            "target_membership": UUID(target.id),
            "target_session": UUID(target_session.id),
        }


def _mutate(database, ids, **overrides):
    values = {
        "tenant_uuid": ids["tenant"],
        "actor_user_uuid": ids["actor_user"],
        "actor_membership_uuid": ids["actor_membership"],
        "actor_session_uuid": ids["actor_session"],
        "target_membership_uuid": ids["target_membership"],
        "expected_target_revision": 1,
        "action": MembershipMutationAction.DISABLE,
        "action_uuid": uuid4(),
        "database_now": NOW,
    }
    values.update(overrides)
    with database.transaction() as session:
        return TenantMembershipService().mutate(session, **values)


def _proof(ids, *, action, role=None):
    return AdminPermissionChangeProof(
        tenant_uuid=ids["tenant"],
        actor_user_uuid=ids["actor_user"],
        actor_session_uuid=ids["actor_session"],
        target_membership_uuid=ids["target_membership"],
        expected_target_revision=1,
        action=action,
        target_role=role,
    )


@pytest.mark.parametrize(
    (
        "current_role",
        "current_status",
        "action",
        "target_role",
        "purpose",
    ),
    [
        ("operator", "active", "change_role", "admin", "grant_admin"),
        ("admin", "active", "change_role", "operator", "revoke_admin"),
        ("admin", "disabled", "enable", None, "grant_admin"),
        ("admin", "active", "disable", None, "revoke_admin"),
        ("operator", "active", "disable", None, None),
    ],
)
def test_membership_plan_is_shared_with_d48_purpose_selection(
    current_role,
    current_status,
    action,
    target_role,
    purpose,
):
    plan = plan_membership_mutation(
        current_role=TenantRole(current_role),
        current_status=current_status,
        action=MembershipMutationAction(action),
        target_role=None if target_role is None else TenantRole(target_role),
    )
    assert plan.admin_sms_purpose == purpose
    assert plan.changes_admin_authority is (purpose is not None)


def test_operator_disable_needs_no_d48_and_revokes_all_target_sessions(database):
    ids = _seed(database)

    result = _mutate(database, ids)

    assert result.status == "disabled"
    assert result.role is TenantRole.OPERATOR
    assert result.row_version == 2
    assert result.sessions_revoked == 1
    with database.new_session() as session:
        user = session.get(User, str(ids["target_user"]))
        target_session = session.get(TenantUserSession, str(ids["target_session"]))
        event = session.scalar(sa.select(TenantAuthSecurityEvent))
        assert user.auth_version == 2
        assert target_session.revoked_reason_code == "membership_security_invalidated"
        assert event.reason_code == "membership_disabled"


def test_only_active_admin_cannot_be_disabled_even_with_exact_proof(database):
    ids = _seed(database)
    ids["target_user"] = ids["actor_user"]
    ids["target_membership"] = ids["actor_membership"]
    ids["target_session"] = ids["actor_session"]
    proof = _proof(ids, action=MembershipMutationAction.DISABLE)

    with pytest.raises(LastActiveAdminError):
        _mutate(database, ids, admin_proof=proof)

    with database.new_session() as session:
        assert (
            session.get(TenantMembership, str(ids["target_membership"])).status
            == "active"
        )


def test_admin_downgrade_requires_exact_d48_and_preserves_one_admin(database):
    ids = _seed(database, target_role="admin", admins=2)
    action = MembershipMutationAction.CHANGE_ROLE

    with pytest.raises(MembershipMutationAuthorityError):
        _mutate(database, ids, action=action, target_role=TenantRole.OPERATOR)

    result = _mutate(
        database,
        ids,
        action=action,
        target_role=TenantRole.OPERATOR,
        admin_proof=_proof(ids, action=action, role=TenantRole.OPERATOR),
    )
    assert result.role is TenantRole.OPERATOR
    assert result.status == "active"


def test_disabled_operator_promotion_requires_d48_before_role_is_staged(database):
    ids = _seed(database, target_status="disabled")
    action = MembershipMutationAction.CHANGE_ROLE

    with pytest.raises(MembershipMutationAuthorityError):
        _mutate(database, ids, action=action, target_role=TenantRole.ADMIN)

    result = _mutate(
        database,
        ids,
        action=action,
        target_role=TenantRole.ADMIN,
        admin_proof=_proof(ids, action=action, role=TenantRole.ADMIN),
    )
    assert result.role is TenantRole.ADMIN
    assert result.status == "disabled"


def test_enabling_operator_recounts_active_and_unexpired_pending_seats(database):
    ids = _seed(database, target_status="disabled")
    with database.transaction() as session:
        for index in range(3, 11):
            user = _user(index)
            session.add(user)
            session.flush()
            session.add(_membership(str(ids["tenant"]), user.id, role="operator"))
        invited = _user(99, status="unverified")
        session.add(invited)
        session.flush()
        session.add(
            TenantInvitation(
                id=str(uuid4()),
                tenant_id=str(ids["tenant"]),
                user_id=invited.id,
                phone_region_iso2="CN",
                phone_e164=invited.phone_e164,
                phone_normalization_version=PHONE_NORMALIZATION_VERSION,
                role_key="operator",
                token_hash=b"t" * 32,
                token_generation=1,
                status="pending",
                expires_at=NOW + timedelta(days=1),
            )
        )

    with pytest.raises(MemberSeatLimitError):
        _mutate(database, ids, action=MembershipMutationAction.ENABLE)

    with database.new_session() as session:
        assert (
            session.get(TenantMembership, str(ids["target_membership"])).status
            == "disabled"
        )


def test_disabled_actor_cannot_mutate_even_if_request_claims_admin(database):
    ids = _seed(database)
    with database.transaction() as session:
        actor = session.get(TenantMembership, str(ids["actor_membership"]))
        actor.status = "disabled"

    with pytest.raises(MembershipMutationAuthorityError):
        _mutate(database, ids)
