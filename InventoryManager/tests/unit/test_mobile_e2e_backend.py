from types import SimpleNamespace

import pytest

from scripts.mobile_e2e_backend import (
    build_database_url,
    select_fixture_warehouse,
    validate_e2e_identifier,
)


@pytest.mark.parametrize(
    "identifier",
    [
        "xianyu_mobile_e2e_test_control",
        "xianyu_mobile_e2e_test_tenant",
        "xianyu_mobile_e2e_test_user",
    ],
)
def test_validate_e2e_identifier_accepts_isolated_names(identifier):
    assert validate_e2e_identifier(identifier) == identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "mysql",
        "inventory_management",
        "xianyu_mobile_control",
        "xianyu_mobile_e2e_test_tenant; DROP DATABASE mysql",
        "../xianyu_mobile_e2e_test_tenant",
    ],
)
def test_validate_e2e_identifier_rejects_non_test_or_unsafe_names(identifier):
    with pytest.raises(ValueError, match="e2e_test"):
        validate_e2e_identifier(identifier)


def test_build_database_url_quotes_credentials_and_selects_exact_database():
    url = build_database_url(
        username="xianyu_mobile_e2e_test_user",
        password="p@ss:/?#[] word",
        host="e2e-db",
        port=3306,
        database="xianyu_mobile_e2e_test_tenant",
    )

    assert url.username == "xianyu_mobile_e2e_test_user"
    assert url.password == "p@ss:/?#[] word"
    assert url.host == "e2e-db"
    assert url.port == 3306
    assert url.database == "xianyu_mobile_e2e_test_tenant"
    assert "p%40ss%3A%2F%3F%23%5B%5D word" in url.render_as_string(
        hide_password=False
    )


def test_fixture_reuses_the_single_migrated_warehouse():
    warehouse = SimpleNamespace(
        province="待配置",
        city="待配置",
        name="默认仓库",
    )

    selected = select_fixture_warehouse([warehouse])

    assert selected is warehouse
    assert (warehouse.province, warehouse.city, warehouse.name) == (
        "广东省",
        "深圳市",
        "E2E 测试仓",
    )


@pytest.mark.parametrize("warehouses", [[], [object(), object()]])
def test_fixture_rejects_a_database_without_exactly_one_warehouse(warehouses):
    with pytest.raises(RuntimeError, match="exactly one migrated warehouse"):
        select_fixture_warehouse(warehouses)
