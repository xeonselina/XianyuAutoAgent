from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control import ControlBase, ControlDatabase
from inventory_control.invitations import (
    InvitationExpirySweep,
    InvitationJoinGateFacts,
    InvitationPersistenceService,
    InvitationRole,
    InvitationToken,
    build_invitation_expiry_capability,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.invitations import TenantInvitation
from inventory_control.models.subscriptions import MemberSeatGuard


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("42000000-0000-4000-8000-000000000001")
USER_UUID = UUID("42000000-0000-4000-8000-000000000002")
FIRST_UUID = UUID("42000000-0000-4000-8000-000000000003")
SECOND_UUID = UUID("42000000-0000-4000-8000-000000000004")


@dataclass
class Gate:
    def __call__(self, _session, *, tenant, database_now):
        del database_now
        return InvitationJoinGateFacts(
            tenant_uuid=UUID(tenant.id),
            access_version=tenant.access_version,
            join_allowed=True,
        )


@pytest.fixture
def database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                status="active",
                access_version=1,
                row_version=1,
            )
        )
        session.add(
            MemberSeatGuard(
                tenant_id=str(TENANT_UUID),
                quota_key="member_seats",
                row_version=1,
            )
        )
    return mysql_control_database


@pytest.fixture
def invitations():
    return InvitationPersistenceService(
        join_gate_current_read=Gate(),
        database_clock=lambda _session: NOW,
    )


def _create(database, invitations, *, invitation_uuid, token):
    with database.transaction() as session:
        return invitations.create_or_resend(
            session,
            tenant_uuid=TENANT_UUID,
            raw_phone="13812345678",
            role=InvitationRole.OPERATOR,
            proposed_token=InvitationToken(token * 43),
            proposed_invitation_uuid=invitation_uuid,
            proposed_user_uuid=USER_UUID,
            expected_tenant_access_version=1,
            expected_invitation_row_version=None,
        )


def test_due_rows_expire_in_bounded_short_transactions(database, invitations):
    first = _create(
        database,
        invitations,
        invitation_uuid=FIRST_UUID,
        token="A",
    )
    with database.transaction() as session:
        session.get(TenantInvitation, str(first.invitation_uuid)).expires_at = (
            NOW - timedelta(seconds=1)
        )

    sweep = InvitationExpirySweep(
        database=database,
        invitations=invitations,
        database_clock=lambda _session: NOW,
    )
    result = sweep.run_once(max_candidates=10)
    replay = sweep.run_once(max_candidates=10)

    assert result.candidate_invitations == 1
    assert result.expired_invitations == 1
    assert result.concurrent_conflicts == 0
    assert replay.candidate_invitations == 0
    with database.new_session() as session:
        row = session.get(TenantInvitation, str(FIRST_UUID))
        assert row.status == "expired"
        assert row.user_id is None
        assert row.terminal_reason_code == "invitation_expired"


def test_shared_process_capability_runs_sweep_once_per_bucket(
    database,
    invitations,
):
    first = _create(
        database,
        invitations,
        invitation_uuid=FIRST_UUID,
        token="A",
    )
    with database.transaction() as session:
        session.get(TenantInvitation, str(first.invitation_uuid)).expires_at = (
            NOW - timedelta(seconds=1)
        )
    capability = build_invitation_expiry_capability(
        database=database,
        invitations=invitations,
        scan_interval=timedelta(seconds=30),
        max_candidates=10,
        database_clock=lambda _session: NOW,
    )

    initial = capability.triggers[0].run_due(now=NOW)
    replay = capability.triggers[0].run_due(now=NOW)

    assert initial.ran is True
    assert initial.value.expired_invitations == 1
    assert replay.ran is False
    with database.new_session() as session:
        assert session.get(TenantInvitation, str(FIRST_UUID)).status == "expired"


def test_future_pending_row_is_not_selected_and_limit_is_explicit(
    database,
    invitations,
):
    created = _create(
        database,
        invitations,
        invitation_uuid=FIRST_UUID,
        token="A",
    )
    result = InvitationExpirySweep(
        database=database,
        invitations=invitations,
        database_clock=lambda _session: NOW,
    ).run_once(max_candidates=1)

    assert result.candidate_invitations == 0
    with database.new_session() as session:
        assert session.get(
            TenantInvitation, str(created.invitation_uuid)
        ).status == "pending"


@pytest.mark.parametrize("limit", [0, 1001, True])
def test_sweep_rejects_implicit_or_unbounded_batch_size(
    database,
    invitations,
    limit,
):
    with pytest.raises(ValueError):
        InvitationExpirySweep(
            database=database,
            invitations=invitations,
            database_clock=lambda _session: NOW,
        ).run_once(max_candidates=limit)
