from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from inventory_control import (
    ControlBase,
    ControlDatabase,
    DatabaseIdentityControlRecord,
    Installation,
    Tenant,
    TenantDatabaseRoute,
)


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_minimal_control_model_graph_persists(control_database):
    now = datetime.now(timezone.utc)
    tenant = Tenant(name=None, slug=None)
    route = TenantDatabaseRoute(
        tenant=tenant,
        database_instance_key="local-test-instance",
        database_name="inventory_management_test",
    )
    route.identity_record = DatabaseIdentityControlRecord(
        tenant_id=tenant.id,
        database_uuid=route.database_uuid,
        expected_schema_generation=1,
        observed_schema_generation=1,
        identity_created_at=now,
        last_verified_at=now,
    )

    with control_database.transaction() as session:
        session.add(Installation(marker_fingerprint="c" * 64))
        session.add(tenant)

    UUID(tenant.id)
    UUID(route.database_uuid)
    assert tenant.status == "provisioning"
    assert tenant.database_route is route
    assert route.identity_record.database_route is route


def test_database_route_is_unique_per_instance_and_name(control_database):
    first_tenant = Tenant()
    second_tenant = Tenant()
    first_route = TenantDatabaseRoute(
        tenant=first_tenant,
        database_instance_key="local-test-instance",
        database_name="inventory_management_test",
    )
    second_route = TenantDatabaseRoute(
        tenant=second_tenant,
        database_instance_key="local-test-instance",
        database_name="inventory_management_test",
    )

    with pytest.raises(IntegrityError):
        with control_database.transaction() as session:
            session.add_all([first_route, second_route])
