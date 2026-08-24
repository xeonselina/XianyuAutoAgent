import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from inventory_control import (
    ControlBase,
    ControlDatabase,
    Tenant,
    TenantInvitation,
    User,
)


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def seed(database):
    with database.transaction() as session:
        tenant = Tenant(status="active")
        user = User(
            phone_e164="+8613812345678",
            phone_normalization_version=1,
            phone_metadata_version="cn-mobile-v1",
            status="active",
        )
        session.add_all((tenant, user))
        session.flush()
        return tenant.id, user.id


def invitation(tenant_id, default_user_id, *, token=b"token-1", **overrides):
    values = {
        "tenant_id": tenant_id,
        "user_id": default_user_id,
        "phone_e164": "+8613812345678",
        "phone_normalization_version": 1,
        "role_key": "operator",
        "token_hash": hashlib.sha256(token).digest(),
        "token_generation": 1,
        "status": "pending",
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return TenantInvitation(**values)


def test_pending_identity_and_hash_are_database_unique(database):
    tenant_id, user_id = seed(database)
    with database.transaction() as session:
        session.add(invitation(tenant_id, user_id))

    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.add(invitation(tenant_id, user_id, token=b"other"))

    other_tenant = Tenant(status="active")
    with database.transaction() as session:
        session.add(other_tenant)
        session.flush()
        session.add(invitation(other_tenant.id, user_id, token=b"cross-tenant"))
    # Cross-tenant pending invitations are permitted, but reusing a bearer
    # digest anywhere is not.
    third_tenant = Tenant(status="active")
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.add(third_tenant)
            session.flush()
            session.add(invitation(third_tenant.id, user_id, token=b"token-1"))


def test_terminal_invitation_releases_user_reference_and_pending_unique_slot(database):
    tenant_id, user_id = seed(database)
    with database.transaction() as session:
        first = invitation(tenant_id, user_id)
        session.add(first)
        session.flush()
        first.status = "superseded"
        first.user_id = None
        first.superseded_at = NOW + timedelta(hours=1)
        first.terminal_reason_code = "membership_claimed_elsewhere"
        session.flush()
        session.add(invitation(tenant_id, user_id, token=b"new-token"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"token_hash": b"short"},
        {"token_generation": 0},
        {"status": "pending", "user_id": None},
        {"status": "accepted", "user_id": None, "accepted_at": None},
        {
            "status": "superseded",
            "user_id": None,
            "superseded_at": NOW,
            "terminal_reason_code": None,
        },
    ],
)
def test_invitation_shape_constraints_fail_closed(database, overrides):
    tenant_id, user_id = seed(database)
    with pytest.raises(DBAPIError):
        with database.transaction() as session:
            session.add(invitation(tenant_id, user_id, **overrides))
