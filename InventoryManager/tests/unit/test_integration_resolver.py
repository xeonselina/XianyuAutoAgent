"""Warehouse/shop scoped integration configuration resolution."""

import os
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.crypto import SecretBox
from app.models.warehouse import (
    Warehouse,
    WarehouseKuaimaiConfig,
    WarehouseSFConfig,
)
from app.models.xianyu_shop import XianyuShop
from app.services.integration_resolver import (
    ConfigurationIncomplete,
    IntegrationResolver,
)
from app.services.printing.kuaimai_service import (
    KuaimaiServiceConfig,
    KuaimaiPrintService,
    get_kuaimai_print_service,
)
from app.services.shipping.sf_express_service import SFServiceConfig
from app.services.xianyu_order_service import XianyuShopConfig
from app.services.settings_service import (
    KUAIMAI_SECRET_PURPOSE,
    SF_CHECKWORD_PURPOSE,
    SF_MONTHLY_CARD_PURPOSE,
    XIANYU_SECRET_PURPOSE,
)


MASTER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class FakeSession:
    def __init__(self, rows):
        self.rows = {
            (
                type(row),
                row.id if hasattr(row, "id") else row.warehouse_id,
            ): row
            for row in rows
        }

    def get(self, model, row_id):
        return self.rows.get((model, row_id))

    def scalars(self, statement):
        self.last_statement = str(statement)
        model = (
            XianyuShop
            if "xianyu_shops" in self.last_statement
            else Warehouse
        )
        rows = [
            row
            for (kind, _row_id), row in self.rows.items()
            if kind is model
        ]
        if model is XianyuShop:
            rows = [row for row in rows if row.is_active]
        return [row.id for row in sorted(rows, key=lambda row: row.id)[:2]]


@pytest.fixture
def configured_resolver():
    box = SecretBox.from_base64(MASTER_KEY)
    warehouses = [
        Warehouse(id=1, province="广东省", city="深圳市", name="仓A"),
        Warehouse(id=2, province="浙江省", city="杭州市", name="仓B"),
    ]
    sf_configs = [
        WarehouseSFConfig(
            warehouse_id=index,
            partner_id="repeat-partner",
            checkword_ciphertext=box.encrypt(
                f"check-{index}", SF_CHECKWORD_PURPOSE
            ),
            monthly_card_ciphertext=box.encrypt(
                f"monthly-{index}", SF_MONTHLY_CARD_PURPOSE
            ),
            test_mode=False,
            sender_name=f"仓{index}寄件人",
            sender_phone=f"1380000000{index}",
            sender_address=f"测试路{index}号",
        )
        for index in (1, 2)
    ]
    kuaimai_configs = [
        WarehouseKuaimaiConfig(
            warehouse_id=index,
            app_id=f"print-{index}",
            app_secret_ciphertext=box.encrypt(
                f"print-secret-{index}", KUAIMAI_SECRET_PURPOSE
            ),
            printer_sn=f"printer-{index}",
        )
        for index in (1, 2)
    ]
    shops = [
        XianyuShop(
            id=index,
            name=f"店{index}",
            app_key=f"shop-key-{index}",
            app_secret_ciphertext=box.encrypt(
                f"shop-secret-{index}", XIANYU_SECRET_PURPOSE
            ),
            is_active=True,
        )
        for index in (11, 12)
    ]
    resolver = IntegrationResolver(
        session=FakeSession(
            warehouses + sf_configs + kuaimai_configs + shops
        ),
        secret_box=box,
        api_domain="open.goofish.pro",
    )
    rentals = {
        1: SimpleNamespace(warehouse_id=1, xianyu_shop_id=11),
        2: SimpleNamespace(warehouse_id=2, xianyu_shop_id=12),
    }
    return resolver, rentals, shops


def test_resolves_two_warehouses_and_shops_without_env_credentials(
    configured_resolver,
    monkeypatch,
):
    resolver, rentals, shops = configured_resolver
    for name in (
        "SF_PARTNER_ID",
        "SF_CHECKWORD",
        "KUAIMAI_APP_SECRET",
        "XIANYU_APP_SECRET",
        "XIANYU_SELLER_ID",
        "XIANYU_SHIP_NAME",
    ):
        monkeypatch.setenv(name, "must-not-be-used")
    monkeypatch.setattr(
        os,
        "getenv",
        lambda *_args, **_kwargs: pytest.fail("business env read"),
    )

    sf_a = resolver.sf_for_rental(rentals[1])
    sf_b = resolver.sf_for_rental(rentals[2])
    assert sf_a.config.partner_id == sf_b.config.partner_id
    assert sf_a.config.sender_name == "仓1寄件人"
    assert sf_b.config.sender_name == "仓2寄件人"
    assert sf_b.config.checkword == "check-2"
    assert resolver.kuaimai_for_rental(rentals[1]).config.printer_sn == (
        "printer-1"
    )
    shop_a = resolver.xianyu_for_rental(rentals[1])
    shop_b = resolver.xianyu_for_shop(shops[1])
    assert shop_a.config.app_secret == "shop-secret-11"
    assert shop_b.config.shop_id == 12
    assert not hasattr(shop_a, "seller_id")
    assert not any(name.startswith("ship_") for name in vars(shop_a))


@pytest.mark.parametrize(
    "config_type",
    [SFServiceConfig, KuaimaiServiceConfig, XianyuShopConfig],
)
def test_client_configs_are_immutable(config_type, configured_resolver):
    resolver, rentals, _shops = configured_resolver
    clients = {
        SFServiceConfig: resolver.sf_for_rental(rentals[1]),
        KuaimaiServiceConfig: resolver.kuaimai_for_rental(rentals[1]),
        XianyuShopConfig: resolver.xianyu_for_rental(rentals[1]),
    }
    with pytest.raises(FrozenInstanceError):
        clients[config_type].config.app_key = "changed"


def test_missing_configuration_exposes_only_scope_id_and_field_names():
    warehouse = Warehouse(
        id=7, province="广东省", city="深圳市", name="未配置仓"
    )
    config = WarehouseSFConfig(
        warehouse_id=7,
        partner_id="partner",
        sender_name="寄件人",
    )
    resolver = IntegrationResolver(
        session=FakeSession([warehouse, config]),
        secret_box=SecretBox.from_base64(MASTER_KEY),
        api_domain="open.goofish.pro",
    )

    with pytest.raises(ConfigurationIncomplete) as caught:
        resolver.sf_for_warehouse(7)

    assert vars(caught.value) == {
        "scope": "warehouse",
        "scope_id": 7,
        "missing_fields": (
            "checkword",
            "monthly_card",
            "sender_phone",
            "sender_address",
        ),
    }
    assert "ciphertext" not in str(caught.value)


@pytest.mark.parametrize(
    "domain",
    [
        "https://open.goofish.pro",
        "open.goofish.pro/path",
        "user@open.goofish.pro",
        "open.goofish.pro?debug=1",
        "open_goofish.pro",
        "-open.goofish.pro",
    ],
)
def test_rejects_non_hostname_xianyu_api_domain(
    configured_resolver,
    domain,
):
    resolver, _rentals, shops = configured_resolver
    resolver.api_domain = domain

    with pytest.raises(ValueError, match="hostname"):
        resolver.xianyu_for_shop(shops[0])


def test_xianyu_requeries_detached_shop_and_only_compat_uses_active(
    configured_resolver,
):
    resolver, _rentals, shops = configured_resolver
    stored = shops[0]
    stored.is_active = False
    detached = SimpleNamespace(
        id=stored.id,
        app_key="detached-key",
        app_secret_ciphertext="detached-secret",
    )

    assert resolver.xianyu_for_shop(detached).config.app_key == stored.app_key
    assert resolver.xianyu_for_only_shop().config.shop_id == shops[1].id
    assert "is_active" in resolver.session.last_statement

    with pytest.raises(ConfigurationIncomplete) as caught:
        resolver.xianyu_for_shop(999)
    assert caught.value.scope_id == 999


@pytest.mark.parametrize(
    ("kind", "field", "purpose"),
    [
        ("checkword", "checkword", SF_CHECKWORD_PURPOSE),
        ("monthly", "monthly_card", SF_MONTHLY_CARD_PURPOSE),
        ("kuaimai", "app_secret", KUAIMAI_SECRET_PURPOSE),
        ("xianyu", "app_secret", XIANYU_SECRET_PURPOSE),
    ],
)
@pytest.mark.parametrize("bad", ["corrupt-canary", "blank"])
def test_bad_secret_is_redacted_configuration_incomplete(
    configured_resolver,
    kind,
    field,
    purpose,
    bad,
):
    resolver, rentals, shops = configured_resolver
    ciphertext = (
        resolver.secret_box.encrypt("", purpose) if bad == "blank" else bad
    )
    if kind in {"checkword", "monthly"}:
        config = resolver.session.get(WarehouseSFConfig, 1)
        attr = {
            "checkword": "checkword_ciphertext",
            "monthly": "monthly_card_ciphertext",
        }[kind]
        setattr(config, attr, ciphertext)
        call = lambda: resolver.sf_for_rental(rentals[1])
        scope, scope_id = "warehouse", 1
    elif kind == "kuaimai":
        config = resolver.session.get(WarehouseKuaimaiConfig, 1)
        config.app_secret_ciphertext = ciphertext
        call = lambda: resolver.kuaimai_for_rental(rentals[1])
        scope, scope_id = "warehouse", 1
    else:
        shops[0].app_secret_ciphertext = ciphertext
        call = lambda: resolver.xianyu_for_shop(shops[0])
        scope, scope_id = "shop", shops[0].id

    with pytest.raises(ConfigurationIncomplete) as caught:
        call()
    assert (
        caught.value.scope,
        caught.value.scope_id,
        caught.value.missing_fields,
    ) == (scope, scope_id, (field,))
    assert caught.value.__suppress_context__
    assert caught.value.__context__ is None
    assert "corrupt-canary" not in str(caught.value)


def test_explicit_falsy_dependencies_do_not_fall_back(configured_resolver):
    resolver, _rentals, shops = configured_resolver

    class FalsySession(FakeSession):
        def __bool__(self):
            return False

    session = FalsySession(resolver.session.rows.values())
    explicit = IntegrationResolver(
        session=session,
        secret_box=resolver.secret_box,
        api_domain="",
    )
    assert explicit.session is session
    with pytest.raises(ValueError, match="hostname"):
        explicit.xianyu_for_shop(shops[0].id)


def test_kuaimai_constructor_is_explicit_and_factory_is_fresh(
    configured_resolver,
    monkeypatch,
):
    resolver, rentals, _shops = configured_resolver
    with pytest.raises(TypeError):
        KuaimaiPrintService()
    monkeypatch.setattr(
        "app.services.integration_resolver.IntegrationResolver",
        lambda: resolver,
    )
    first = get_kuaimai_print_service(rental=rentals[1])
    second = get_kuaimai_print_service(rental=rentals[1])
    assert first is not second
