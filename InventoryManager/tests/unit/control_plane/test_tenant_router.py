import uuid
from dataclasses import replace

import pytest

from app.tenancy import (
    PlatformTenantReadContext,
    TenantContext,
    TenantContextSource,
    TenancyError,
    TenancyErrorCode,
)
from inventory_control.crypto import (
    RootKey,
    derive_platform_read_password,
    derive_tenant_dml_password,
)
from inventory_control.routing import (
    AccountKind,
    AccountLoginState,
    PlatformTenantReadRouter,
    TenantDatabaseRouter,
    TenantRoute,
    TenantRouteStatus,
)


TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
DATABASE_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PLATFORM_ADMIN = uuid.UUID("33333333-3333-4333-8333-333333333333")
PLATFORM_SESSION = uuid.UUID("44444444-4444-4444-8444-444444444444")
ROOT_MATERIAL = bytes(range(32))


def context(*, tenant_id=TENANT_A, access_version=7):
    return TenantContext(
        tenant_id=tenant_id,
        access_version=access_version,
        source=TenantContextSource.WEB_SESSION,
        principal_ref="user:test",
        source_ref="session:test",
        request_id="request-test",
    )


def platform_context(*, tenant_id=TENANT_A, access_version=7):
    return PlatformTenantReadContext(
        target_tenant_id=tenant_id,
        target_access_version=access_version,
        platform_admin_id=PLATFORM_ADMIN,
        platform_session_id=PLATFORM_SESSION,
        read_policy_version=1,
        request_id="platform-request-test",
    )


def route(
    *,
    tenant_uuid=TENANT_A,
    tenant_access_version=7,
    status=TenantRouteStatus.READY,
    account_kind=AccountKind.DML,
    database_uuid=DATABASE_A,
    username="tenant_a_dml_g1",
    credential_generation=1,
    root_key_version=1,
    derivation_version=1,
    route_version=1,
    desired_login_state=AccountLoginState.ACTIVE,
):
    return TenantRoute(
        tenant_uuid=tenant_uuid,
        tenant_access_version=tenant_access_version,
        status=status,
        account_kind=account_kind,
        database_uuid=database_uuid,
        database_instance_key="primary",
        database_name="tenant_a_database",
        username=username,
        credential_generation=credential_generation,
        root_key_version=root_key_version,
        derivation_version=derivation_version,
        route_version=route_version,
        desired_login_state=desired_login_state,
        expected_schema_generation=1,
    )


class FakeRouteRepository:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.error = None

    def get_current_ready_route(
        self, *, tenant_uuid, access_version, account_kind
    ):
        self.calls.append((tenant_uuid, access_version, account_kind))
        if self.error is not None:
            raise self.error
        return self.routes.get(account_kind)


class FakeRootKeyProvider:
    def __init__(self, keys=None):
        self.keys = keys or {1: RootKey(version=1, material=ROOT_MATERIAL)}
        self.calls = []

    def get_root_key(self, *, version):
        self.calls.append(version)
        return self.keys[version]


class FakeEngine:
    def __init__(self, identity):
        self.identity = identity
        self.dispose_calls = 0
        self.dispose_error = None

    def dispose(self):
        self.dispose_calls += 1
        if self.dispose_error is not None:
            raise self.dispose_error

    def __repr__(self):
        return f"FakeEngine(identity={self.identity!r})"


class FakeEngineFactory:
    def __init__(self):
        self.calls = []
        self.engines = []
        self.failure = None

    def create(self, *, route, identity, password):
        self.calls.append((route, identity, password))
        if self.failure is not None:
            if self.failure == "echo-password":
                raise RuntimeError(f"factory failed for {password}")
            raise self.failure
        engine = FakeEngine(identity)
        self.engines.append(engine)
        return engine


class FakeIdentityVerifier:
    def __init__(self):
        self.calls = []
        self.failure = None

    def verify(self, *, engine, expected):
        self.calls.append((engine, expected))
        if self.failure is not None:
            raise self.failure


def build_router(routes, *, keys=None):
    repository = FakeRouteRepository(routes)
    root_keys = FakeRootKeyProvider(keys)
    factory = FakeEngineFactory()
    verifier = FakeIdentityVerifier()
    router = TenantDatabaseRouter(
        repository=repository,
        root_key_provider=root_keys,
        engine_factory=factory,
        identity_verifier=verifier,
        max_cache_entries=4,
    )
    return router, repository, root_keys, factory, verifier


def assert_error_code(caught, code):
    assert caught.value.code == code.value


def assert_secret_absent_from_exception_tree(error, secret):
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        assert secret not in str(current)
        assert secret not in repr(current)
        pending.extend((current.__cause__, current.__context__))


def test_dml_route_uses_only_context_and_caches_verified_engine():
    dml_route = route()
    router, repository, root_keys, factory, verifier = build_router(
        {AccountKind.DML: dml_route}
    )

    first = router.get_engine(context(), account_kind=AccountKind.DML)
    second = router.get_engine(context(), account_kind=AccountKind.DML)

    assert first is second
    assert repository.calls == [
        (TENANT_A, 7, AccountKind.DML),
        (TENANT_A, 7, AccountKind.DML),
    ]
    assert root_keys.calls == [1]
    assert len(factory.calls) == 1
    created_route, identity, password = factory.calls[0]
    assert created_route is dml_route
    assert identity == dml_route.routing_identity()
    assert password == derive_tenant_dml_password(
        root_key=RootKey(version=1, material=ROOT_MATERIAL),
        tenant_uuid=TENANT_A,
        database_uuid=DATABASE_A,
        account_username="tenant_a_dml_g1",
        credential_generation=1,
        derivation_version=1,
    )
    assert len(verifier.calls) == 1
    _, expected = verifier.calls[0]
    assert expected.tenant_id == TENANT_A
    assert expected.database_uuid == DATABASE_A
    assert expected.schema_generation == 1
    assert password not in repr(router)
    assert password not in repr(dml_route)


def test_dml_and_platform_read_use_different_derivation_and_engines():
    dml_route = route()
    read_route = route(
        account_kind=AccountKind.PLATFORM_READ,
        username="tenant_a_read_g1",
    )
    router, _, _, factory, verifier = build_router(
        {
            AccountKind.DML: dml_route,
            AccountKind.PLATFORM_READ: read_route,
        }
    )

    platform_router = PlatformTenantReadRouter(router)
    dml_engine = router.get_engine(context(), account_kind=AccountKind.DML)
    read_engine = platform_router.get_engine(platform_context())

    assert dml_engine is not read_engine
    assert len(verifier.calls) == 2
    dml_password = factory.calls[0][2]
    read_password = factory.calls[1][2]
    assert dml_password != read_password
    assert read_password == derive_platform_read_password(
        root_key=RootKey(version=1, material=ROOT_MATERIAL),
        tenant_uuid=TENANT_A,
        database_uuid=DATABASE_A,
        account_username="tenant_a_read_g1",
        credential_generation=1,
        derivation_version=1,
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.PLATFORM_READ)
    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)

    with pytest.raises(TenancyError) as caught:
        platform_router.get_engine(context())
    assert_error_code(caught, TenancyErrorCode.TENANT_CONTEXT_REQUIRED)


def test_stale_context_access_version_fails_closed_and_evicts_old_engine():
    ready_route = route()
    router, repository, _, factory, _ = build_router(
        {AccountKind.DML: ready_route}
    )
    engine = router.get_engine(context(), account_kind=AccountKind.DML)
    repository.routes[AccountKind.DML] = replace(
        ready_route, tenant_access_version=8
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(access_version=7), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.STALE_TENANT_ACCESS_VERSION)
    assert engine.dispose_calls == 1
    assert len(factory.calls) == 1


@pytest.mark.parametrize(
    "route_change",
    [
        {"status": TenantRouteStatus.PROVISIONAL},
        {"desired_login_state": AccountLoginState.LOCKED},
    ],
)
def test_unready_or_locked_route_fails_closed_and_evicts(route_change):
    ready_route = route()
    router, repository, _, factory, _ = build_router(
        {AccountKind.DML: ready_route}
    )
    engine = router.get_engine(context(), account_kind=AccountKind.DML)
    repository.routes[AccountKind.DML] = replace(ready_route, **route_change)

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert engine.dispose_calls == 1
    assert len(factory.calls) == 1


@pytest.mark.parametrize(
    "mismatched_route",
    [
        route(tenant_uuid=TENANT_B),
        route(account_kind=AccountKind.PLATFORM_READ),
    ],
)
def test_repository_route_mismatch_fails_before_key_or_factory(mismatched_route):
    router, _, root_keys, factory, verifier = build_router(
        {AccountKind.DML: mismatched_route}
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert root_keys.calls == []
    assert factory.calls == []
    assert verifier.calls == []


def test_identity_mismatch_disposes_failed_engine_and_never_caches_it():
    router, _, _, factory, verifier = build_router({AccountKind.DML: route()})
    verifier.failure = TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)
    failed_engine = factory.engines[0]
    assert failed_engine.dispose_calls == 1

    verifier.failure = None
    replacement = router.get_engine(context(), account_kind=AccountKind.DML)
    assert replacement is not failed_engine
    assert len(factory.engines) == 2
    assert failed_engine.dispose_calls == 1


def test_factory_error_is_redacted_and_does_not_cache():
    router, _, _, factory, verifier = build_router({AccountKind.DML: route()})
    factory.failure = "echo-password"
    expected_password = derive_tenant_dml_password(
        root_key=RootKey(version=1, material=ROOT_MATERIAL),
        tenant_uuid=TENANT_A,
        database_uuid=DATABASE_A,
        account_username="tenant_a_dml_g1",
        credential_generation=1,
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert_secret_absent_from_exception_tree(caught.value, expected_password)
    assert verifier.calls == []

    factory.failure = None
    router.get_engine(context(), account_kind=AccountKind.DML)
    assert len(factory.calls) == 2


def test_missing_or_wrong_root_key_version_fails_before_factory():
    wrong_key = RootKey(version=2, material=ROOT_MATERIAL)
    router, _, _, factory, _ = build_router(
        {AccountKind.DML: route()},
        keys={1: wrong_key},
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert factory.calls == []


def test_missing_route_and_untrusted_context_fail_closed():
    router, repository, _, factory, _ = build_router({})

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)
    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert factory.calls == []

    with pytest.raises(TenancyError) as caught:
        router.get_engine(TENANT_A, account_kind=AccountKind.DML)
    assert_error_code(caught, TenancyErrorCode.TENANT_CONTEXT_REQUIRED)
    assert len(repository.calls) == 1

    with pytest.raises(TypeError):
        router.get_engine(
            context(),
            account_kind=AccountKind.DML,
            tenant_uuid=TENANT_B,
        )


def test_router_invalidation_accepts_context_not_selectors():
    router, _, _, _, _ = build_router(
        {
            AccountKind.DML: route(),
            AccountKind.PLATFORM_READ: route(
                account_kind=AccountKind.PLATFORM_READ,
                username="tenant_a_read_g1",
            ),
        }
    )
    platform_router = PlatformTenantReadRouter(router)
    dml = router.get_engine(context(), account_kind=AccountKind.DML)
    read = platform_router.get_engine(platform_context())

    assert (
        router.invalidate_purpose(context(), account_kind=AccountKind.DML) == 1
    )
    assert dml.dispose_calls == 1
    assert read.dispose_calls == 0
    assert platform_router.invalidate_tenant(platform_context()) == 1
    assert read.dispose_calls == 1
    assert router.invalidate_tenant(context()) == 0

    with pytest.raises(TenancyError) as caught:
        router.invalidate_tenant(TENANT_A)
    assert_error_code(caught, TenancyErrorCode.TENANT_CONTEXT_REQUIRED)


def test_dispose_error_is_redacted_and_removed_entry_is_not_reused():
    router, _, _, factory, _ = build_router({AccountKind.DML: route()})
    engine = router.get_engine(context(), account_kind=AccountKind.DML)
    password = factory.calls[0][2]
    engine.dispose_error = RuntimeError(f"dispose failed for {password}")

    with pytest.raises(TenancyError) as caught:
        router.invalidate_purpose(context(), account_kind=AccountKind.DML)

    assert_error_code(caught, TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
    assert_secret_absent_from_exception_tree(caught.value, password)
    assert engine.dispose_calls == 1

    replacement = router.get_engine(context(), account_kind=AccountKind.DML)
    assert replacement is not engine
    assert len(factory.engines) == 2
    PlatformTenantReadRouter,
