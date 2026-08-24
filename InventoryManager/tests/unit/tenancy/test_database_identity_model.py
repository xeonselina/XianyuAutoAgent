from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models.database_identity import TenantDatabaseIdentity


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def identity(**overrides):
    values = {
        "tenant_id": str(uuid4()),
        "database_uuid": str(uuid4()),
        "schema_generation": 1,
    }
    values.update(overrides)
    return TenantDatabaseIdentity(**values)


def test_database_identity_persists_one_canonical_row(application):
    record = identity()
    record.validate_uuid_fields()
    db.session.add(record)
    db.session.commit()

    stored = db.session.get(TenantDatabaseIdentity, 1)
    assert stored is record
    assert UUID(stored.tenant_id)
    assert UUID(stored.database_uuid)
    assert stored.schema_generation == 1


def test_database_identity_singleton_constraint_rejects_a_second_row(application):
    first = identity()
    second = identity(singleton_key=2)
    db.session.add(first)
    db.session.commit()

    db.session.add(second)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": "not-a-uuid"},
        {"database_uuid": str(UUID(int=0))},
        {"schema_generation": 0},
    ],
)
def test_database_identity_validation_rejects_invalid_fields(overrides):
    with pytest.raises(ValueError):
        identity(**overrides).validate_uuid_fields()
