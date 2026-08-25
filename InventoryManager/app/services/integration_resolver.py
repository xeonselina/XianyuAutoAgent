"""Resolve integration clients from the current tenant business database."""

from flask import current_app
from sqlalchemy import select

from app import db
from app.models.warehouse import (
    Warehouse,
    WarehouseKuaimaiConfig,
    WarehouseSFConfig,
)
from app.models.xianyu_shop import XianyuShop
from app.services.printing.kuaimai_service import (
    KuaimaiPrintService,
    KuaimaiServiceConfig,
)
from app.services.settings_service import (
    KUAIMAI_SECRET_PURPOSE,
    SF_CHECKWORD_PURPOSE,
    SF_MONTHLY_CARD_PURPOSE,
    XIANYU_SECRET_PURPOSE,
)
from app.services.shipping.sf_express_service import (
    SFExpressService,
    SFServiceConfig,
)
from app.services.xianyu_order_service import (
    XianyuOrderService,
    XianyuShopConfig,
)


class ConfigurationIncomplete(RuntimeError):
    """One warehouse or shop lacks named public configuration fields."""

    def __init__(self, scope, scope_id, missing_fields):
        self.scope = scope
        self.scope_id = scope_id
        self.missing_fields = tuple(missing_fields)
        fields = ",".join(self.missing_fields)
        super().__init__(f"{scope} {scope_id} missing {fields}")


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


class IntegrationResolver:
    """Build fresh clients for one explicit warehouse or shop."""

    def __init__(
        self,
        session=None,
        secret_box=None,
        api_domain=None,
    ):
        self.session = session or db.session
        self.secret_box = secret_box
        self.api_domain = api_domain

    def _secret_box(self):
        if self.secret_box is not None:
            return self.secret_box
        store = current_app.extensions.get("control_store")
        if store is None:
            raise RuntimeError("integration secret box unavailable")
        return store.secret_box

    def _api_domain(self):
        return self.api_domain or current_app.config["XIANYU_API_DOMAIN"]

    def _only_id(self, model, scope, field):
        ids = list(
            self.session.scalars(
                select(model.id).order_by(model.id).limit(2)
            )
        )
        if len(ids) != 1:
            raise ConfigurationIncomplete(scope, None, (field,))
        return ids[0]

    def sf_for_rental(self, rental):
        warehouse_id = getattr(rental, "warehouse_id", None)
        if warehouse_id is None:
            raise ConfigurationIncomplete(
                "warehouse", None, ("warehouse_id",)
            )
        return self.sf_for_warehouse(warehouse_id)

    def sf_for_only_warehouse(self):
        return self.sf_for_warehouse(
            self._only_id(Warehouse, "warehouse", "warehouse_id")
        )

    def sf_for_warehouse(self, warehouse_id):
        warehouse = self.session.get(Warehouse, warehouse_id)
        config = self.session.get(WarehouseSFConfig, warehouse_id)
        values = {
            "partner_id": getattr(config, "partner_id", None),
            "checkword": getattr(config, "checkword_ciphertext", None),
            "monthly_card": getattr(
                config, "monthly_card_ciphertext", None
            ),
            "sender_name": getattr(config, "sender_name", None),
            "sender_phone": getattr(config, "sender_phone", None),
            "sender_address": getattr(config, "sender_address", None),
            "province": getattr(warehouse, "province", None),
            "city": getattr(warehouse, "city", None),
        }
        missing = tuple(name for name, value in values.items() if _blank(value))
        if missing:
            raise ConfigurationIncomplete("warehouse", warehouse_id, missing)
        box = self._secret_box()
        return SFExpressService(
            SFServiceConfig(
                partner_id=values["partner_id"],
                checkword=box.decrypt(
                    values["checkword"], SF_CHECKWORD_PURPOSE
                ),
                monthly_card=box.decrypt(
                    values["monthly_card"], SF_MONTHLY_CARD_PURPOSE
                ),
                test_mode=bool(config.test_mode),
                sender_name=values["sender_name"],
                sender_phone=values["sender_phone"],
                sender_address=values["sender_address"],
                province=values["province"],
                city=values["city"],
            )
        )

    def kuaimai_for_rental(self, rental):
        warehouse_id = getattr(rental, "warehouse_id", None)
        if warehouse_id is None:
            raise ConfigurationIncomplete(
                "warehouse", None, ("warehouse_id",)
            )
        return self.kuaimai_for_warehouse(warehouse_id)

    def kuaimai_for_only_warehouse(self):
        return self.kuaimai_for_warehouse(
            self._only_id(Warehouse, "warehouse", "warehouse_id")
        )

    def kuaimai_for_warehouse(self, warehouse_id):
        config = self.session.get(WarehouseKuaimaiConfig, warehouse_id)
        values = {
            "app_id": getattr(config, "app_id", None),
            "app_secret": getattr(
                config, "app_secret_ciphertext", None
            ),
            "printer_sn": getattr(config, "printer_sn", None),
        }
        missing = tuple(name for name, value in values.items() if _blank(value))
        if missing:
            raise ConfigurationIncomplete("warehouse", warehouse_id, missing)
        return KuaimaiPrintService(
            KuaimaiServiceConfig(
                app_id=values["app_id"],
                app_secret=self._secret_box().decrypt(
                    values["app_secret"], KUAIMAI_SECRET_PURPOSE
                ),
                printer_sn=values["printer_sn"],
            )
        )

    def xianyu_for_rental(self, rental):
        shop_id = getattr(rental, "xianyu_shop_id", None)
        if shop_id is None:
            raise ConfigurationIncomplete("shop", None, ("xianyu_shop_id",))
        return self.xianyu_for_shop(shop_id)

    def xianyu_for_only_shop(self):
        return self.xianyu_for_shop(
            self._only_id(XianyuShop, "shop", "xianyu_shop_id")
        )

    def xianyu_for_shop(self, shop):
        if not isinstance(shop, XianyuShop):
            shop = self.session.get(XianyuShop, shop)
        shop_id = getattr(shop, "id", None)
        values = {
            "app_key": getattr(shop, "app_key", None),
            "app_secret": getattr(shop, "app_secret_ciphertext", None),
        }
        missing = tuple(name for name, value in values.items() if _blank(value))
        if missing:
            raise ConfigurationIncomplete("shop", shop_id, missing)
        config = XianyuShopConfig(
            shop_id=shop_id,
            app_key=values["app_key"],
            app_secret=self._secret_box().decrypt(
                values["app_secret"], XIANYU_SECRET_PURPOSE
            ),
        )
        return XianyuOrderService(config, self._api_domain())
