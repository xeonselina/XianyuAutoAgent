import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from inventory_control.routing import (
    AccountKind,
    BoundedEngineCache,
    RoutingIdentity,
    StaleRoutingIdentityError,
)


TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
DATABASE_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DATABASE_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class FakeEngine:
    def __init__(self, identity):
        self.identity = identity
        self.dispose_calls = 0
        self._lock = threading.Lock()

    def dispose(self):
        with self._lock:
            self.dispose_calls += 1


class FakeFactory:
    def __init__(self):
        self.created = []
        self._lock = threading.Lock()

    def __call__(self, identity):
        engine = FakeEngine(identity)
        with self._lock:
            self.created.append(engine)
        return engine


def identity(
    *,
    tenant_uuid=TENANT_A,
    database_uuid=DATABASE_A,
    account_kind=AccountKind.DML,
    username="tenant_a_dml_g1",
    credential_generation=1,
    root_key_version=1,
    derivation_version=1,
    route_version=1,
):
    return RoutingIdentity(
        tenant_uuid=tenant_uuid,
        account_kind=account_kind,
        database_uuid=database_uuid,
        username=username,
        credential_generation=credential_generation,
        root_key_version=root_key_version,
        derivation_version=derivation_version,
        route_version=route_version,
    )


def test_routing_identity_is_immutable_normalized_and_complete():
    route = identity(
        tenant_uuid=str(TENANT_A),
        database_uuid=str(DATABASE_A),
        account_kind="dml",
    )

    assert route.tenant_uuid == TENANT_A
    assert route.database_uuid == DATABASE_A
    assert route.account_kind is AccountKind.DML
    assert route.purpose_scope == (DATABASE_A, AccountKind.DML)
    assert hash(route)
    with pytest.raises(FrozenInstanceError):
        route.route_version = 2

    with pytest.raises(TypeError):
        RoutingIdentity(tenant_uuid=TENANT_A)
    with pytest.raises(ValueError):
        identity(route_version=0)
    with pytest.raises(ValueError):
        identity(account_kind="unknown")


@pytest.mark.parametrize("max_entries", [0, -1, True, 1.5])
def test_cache_requires_a_positive_integer_bound(max_entries):
    with pytest.raises(ValueError):
        BoundedEngineCache(max_entries=max_entries, factory=FakeFactory())


def test_exact_identity_reuses_one_engine_and_never_tenant_id_alone():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=4, factory=factory)
    first_identity = identity()

    first = cache.get_or_create(first_identity)
    same = cache.get_or_create(identity())
    another_database = cache.get_or_create(
        identity(database_uuid=DATABASE_B, username="tenant_a_db_b_dml_g1")
    )

    assert first is same
    assert another_database is not first
    assert len(factory.created) == 2
    assert cache.get(first_identity) is first


def test_lru_promotes_on_get_and_disposes_eviction_exactly_once():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=2, factory=factory)
    route_a = identity()
    route_b = identity(
        tenant_uuid=TENANT_B,
        database_uuid=DATABASE_B,
        username="tenant_b_dml_g1",
    )
    route_c = identity(
        database_uuid=uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        username="tenant_a_db_c_dml_g1",
    )

    engine_a = cache.get_or_create(route_a)
    engine_b = cache.get_or_create(route_b)
    assert cache.get(route_a) is engine_a
    engine_c = cache.get_or_create(route_c)

    assert cache.identities() == (route_a, route_c)
    assert cache.get(route_b) is None
    assert engine_b.dispose_calls == 1
    assert engine_a.dispose_calls == 0
    assert engine_c.dispose_calls == 0

    assert cache.clear() == 2
    assert cache.clear() == 0
    assert engine_a.dispose_calls == 1
    assert engine_b.dispose_calls == 1
    assert engine_c.dispose_calls == 1


def test_new_route_identity_actively_retires_old_generation():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=4, factory=factory)
    generation_one = identity()
    generation_two = identity(
        username="tenant_a_dml_g2",
        credential_generation=2,
        root_key_version=2,
        derivation_version=1,
        route_version=2,
    )

    old_engine = cache.get_or_create(generation_one)
    new_engine = cache.get_or_create(generation_two)

    assert old_engine is not new_engine
    assert old_engine.dispose_calls == 1
    assert new_engine.dispose_calls == 0
    assert cache.get(generation_one) is None
    assert cache.get(generation_two) is new_engine
    assert len(cache) == 1

    with pytest.raises(StaleRoutingIdentityError):
        cache.get_or_create(generation_one)
    assert cache.get(generation_two) is new_engine
    assert new_engine.dispose_calls == 0
    assert len(factory.created) == 2


def test_dml_and_platform_read_never_reuse_or_retire_each_other():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=4, factory=factory)
    dml_v1 = identity()
    read_v1 = identity(
        account_kind=AccountKind.PLATFORM_READ,
        username="tenant_a_read_g1",
    )

    dml_engine = cache.get_or_create(dml_v1)
    read_engine = cache.get_or_create(read_v1)
    dml_v2_engine = cache.get_or_create(
        identity(
            username="tenant_a_dml_g2",
            credential_generation=2,
            route_version=2,
        )
    )

    assert dml_engine is not read_engine
    assert dml_engine.dispose_calls == 1
    assert read_engine.dispose_calls == 0
    assert cache.get(read_v1) is read_engine
    assert (
        cache.get(
            identity(
                route_version=2,
                credential_generation=2,
                username="tenant_a_dml_g2",
            )
        )
        is dml_v2_engine
    )


def test_suspension_and_deletion_style_invalidation_dispose_once():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=8, factory=factory)
    tenant_a_dml = cache.get_or_create(identity())
    tenant_a_read = cache.get_or_create(
        identity(
            account_kind=AccountKind.PLATFORM_READ,
            username="tenant_a_read_g1",
        )
    )
    tenant_b_dml = cache.get_or_create(
        identity(
            tenant_uuid=TENANT_B,
            database_uuid=DATABASE_B,
            username="tenant_b_dml_g1",
        )
    )

    # Suspension locks tenant DML without implicitly borrowing or disposing the
    # separately authorized platform-read purpose.
    assert (
        cache.invalidate_purpose(
            tenant_uuid=TENANT_A,
            account_kind=AccountKind.DML,
        )
        == 1
    )
    assert tenant_a_dml.dispose_calls == 1
    assert tenant_a_read.dispose_calls == 0
    assert tenant_b_dml.dispose_calls == 0

    # Tenant deletion clears every remaining purpose for that tenant.
    assert cache.invalidate_tenant(TENANT_A) == 1
    assert tenant_a_read.dispose_calls == 1
    assert cache.invalidate_tenant(TENANT_A) == 0

    assert cache.invalidate_database(DATABASE_B) == 1
    assert tenant_b_dml.dispose_calls == 1
    assert cache.invalidate_database(DATABASE_B) == 0


def test_purpose_invalidation_is_scoped_and_requires_explicit_selector():
    factory = FakeFactory()
    cache = BoundedEngineCache(max_entries=8, factory=factory)
    dml = cache.get_or_create(identity())
    read = cache.get_or_create(
        identity(
            account_kind=AccountKind.PLATFORM_READ,
            username="tenant_a_read_g1",
        )
    )

    assert (
        cache.invalidate_purpose(
            tenant_uuid=TENANT_A,
            account_kind=AccountKind.DML,
        )
        == 1
    )
    assert dml.dispose_calls == 1
    assert read.dispose_calls == 0
    assert cache.get(read.identity) is read
    with pytest.raises(ValueError):
        cache.invalidate()


def test_concurrent_get_or_create_calls_factory_once():
    creation_started = threading.Event()
    allow_creation = threading.Event()
    creation_count = 0
    count_lock = threading.Lock()

    def blocking_factory(route):
        nonlocal creation_count
        with count_lock:
            creation_count += 1
        creation_started.set()
        assert allow_creation.wait(timeout=5)
        return FakeEngine(route)

    cache = BoundedEngineCache(max_entries=2, factory=blocking_factory)
    route = identity()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cache.get_or_create, route) for _ in range(8)]
        assert creation_started.wait(timeout=5)
        allow_creation.set()
        engines = [future.result(timeout=5) for future in futures]

    assert creation_count == 1
    assert all(engine is engines[0] for engine in engines)
    assert engines[0].dispose_calls == 0
    assert cache.clear() == 1
    assert engines[0].dispose_calls == 1
