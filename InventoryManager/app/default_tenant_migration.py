"""One-time, idempotent adoption of the legacy business database."""

import json
import logging
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import inspect, select, text

from app import db
from app.auth import normalize_china_phone
from app.control.models import Tenant, TenantMember
from app.crypto import hash_token
from app.models.warehouse import (
    Warehouse,
    WarehouseKuaimaiConfig,
    WarehouseSFConfig,
)
from app.models.xianyu_shop import XianyuShop
from app.provisioning import format_tenant_identifiers, validate_tenant_expiration
from app.services.settings_service import SettingsService
from app.tenant_context import bind_tenant, reset_tenant


LOGGER = logging.getLogger(__name__)
BACKUP_HEAD = "20260807_damage_notes"
KNOWN_HEADS = {
    BACKUP_HEAD,
    "20260825_audit_schema",
    "20260824_saas_lite_expand",
    "20260824_saas_lite_contract",
}
CURRENT_HEAD = "20260824_saas_lite_contract"
_IDENTIFIER = re.compile(r"^[a-z0-9_]{1,64}$")
_SAAS_TABLES = {
    "warehouses",
    "warehouse_sf_configs",
    "warehouse_kuaimai_configs",
    "xianyu_shops",
    "xianyu_order_sync_state",
}
_PREFLIGHT_ISSUES = {
    "orphan_rental_devices",
    "orphan_parent_rentals",
    "blank_alert_orders",
}


@dataclass
class MigrationReport:
    target: str
    head: str
    tenant_id: int | None = None
    warehouse_id: int | None = None
    shop_id: int | None = None
    before_counts: dict[str, int] = field(default_factory=dict)
    after_counts: dict[str, int] = field(default_factory=dict)
    issue_counts: dict[str, int] = field(default_factory=dict)
    sf_config_complete: bool = False
    kuaimai_config_complete: bool = False
    xianyu_config_complete: bool = False

    def to_dict(self):
        return asdict(self)


class MigrationRejected(RuntimeError):
    def __init__(self, report):
        super().__init__("Default tenant preflight failed.")
        self.report = report


class MigrationFailed(RuntimeError):
    pass


def _parse_expiration(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid expiration")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return validate_tenant_expiration(parsed)


class DefaultTenantMigrator:
    def __init__(
        self,
        *,
        store,
        provisioner,
        registry,
        name,
        admin_phone,
        expires_at,
        database_name,
        province,
        city,
        confirm_maintenance=None,
        confirm_backup=None,
        environment=None,
        logger=None,
    ):
        self.store = store
        self.provisioner = provisioner
        self.registry = registry
        self.name = provisioner._normalize_name(name)
        self.phone = normalize_china_phone(admin_phone)
        self.expires_at = validate_tenant_expiration(expires_at)
        self.database_name = database_name
        self.province = province
        self.city = city
        self.confirm_maintenance = confirm_maintenance
        self.confirm_backup = confirm_backup
        self.environment = environment if environment is not None else os.environ
        self.logger = logger or LOGGER
        self.report = None
        self._legacy_sync = None

    def _validate_target(self):
        if not isinstance(self.database_name, str) or not _IDENTIFIER.fullmatch(
            self.database_name
        ):
            raise ValueError("unsafe migration target")
        if self.database_name == "inventory_management":
            if (
                self.confirm_maintenance != "maintenance-enabled"
                or self.confirm_backup != "backup-verified"
            ):
                raise ValueError("production confirmations are required")
        elif "test" not in self.database_name:
            raise ValueError("non-production target must contain test")

    def _matching_tenant(self):
        with self.store.session() as session:
            return session.scalar(
                select(Tenant).where(Tenant.db_name == self.database_name)
            )

    @staticmethod
    def _count_tables(connection, names=None):
        table_names = inspect(connection).get_table_names()
        if names is not None:
            table_names = [name for name in names if name in table_names]
        preparer = connection.dialect.identifier_preparer
        return {
            name: connection.scalar(
                text(f"SELECT count(*) FROM {preparer.quote_identifier(name)}")
            )
            for name in sorted(table_names)
        }

    @staticmethod
    def _health_counts(connection):
        return {
            "orphan_rental_devices": connection.scalar(text(
                "SELECT count(*) FROM rentals r LEFT JOIN devices d "
                "ON d.id=r.device_id WHERE d.id IS NULL"
            )),
            "orphan_parent_rentals": connection.scalar(text(
                "SELECT count(*) FROM rentals r LEFT JOIN rentals p "
                "ON p.id=r.parent_rental_id WHERE r.parent_rental_id "
                "IS NOT NULL AND p.id IS NULL"
            )),
            "blank_alert_orders": connection.scalar(text(
                "SELECT count(*) FROM xianyu_order_alerts "
                "WHERE NULLIF(TRIM(order_no), '') IS NULL"
            )),
            "null_device_warehouses": 0,
            "null_rental_warehouses": 0,
            "null_alert_shops": 0,
            "parent_child_warehouse_mismatches": 0,
        }

    def preflight(self):
        self._validate_target()
        with db.engine.connect() as connection:
            if connection.scalar(text("SELECT DATABASE()")) != self.database_name:
                raise ValueError("configured database does not match target")
            head_rows = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all()
            if len(head_rows) != 1:
                raise ValueError("database migration head is invalid")
            head = head_rows[0]
            tenant = self._matching_tenant()
            if head not in KNOWN_HEADS or (tenant is None and head != BACKUP_HEAD):
                raise ValueError("database migration head is not adoptable")
            counts = self._count_tables(connection)
            issues = self._health_counts(connection)
            if "xianyu_order_sync_state" in counts:
                self._legacy_sync = connection.execute(text(
                    "SELECT last_success_at, last_error FROM "
                    "xianyu_order_sync_state ORDER BY id LIMIT 1"
                )).one_or_none()
        self.report = MigrationReport(
            target=self.database_name,
            head=head,
            before_counts=counts,
            issue_counts=issues,
        )
        return self.report

    def _upsert_control(self):
        locks = (
            f"default-db-{hash_token(self.database_name)[:48]}",
            f"tenant-phone-{hash_token(self.phone)[:48]}",
        )
        with self.store.locked_session(locks, timeout=5) as session:
            tenant = session.scalar(
                select(Tenant).where(Tenant.db_name == self.database_name)
            )
            phone_member = session.scalar(
                select(TenantMember).where(TenantMember.phone == self.phone)
            )
            if phone_member is not None and (
                tenant is None or phone_member.tenant_id != tenant.id
            ):
                raise ValueError("admin phone belongs to another tenant")
            if tenant is None:
                encrypted = self.store.secret_box.encrypt(
                    secrets.token_urlsafe(32), purpose="tenant-db-password"
                )
                tenant = Tenant(
                    name=self.name,
                    status="active",
                    expires_at=self.expires_at,
                    db_name=self.database_name,
                    db_username=f"pending_{secrets.token_hex(8)}",
                    db_password_ciphertext=encrypted,
                    provisioning_status="provisioning",
                )
                session.add(tenant)
                session.flush()
                tenant.db_username = format_tenant_identifiers(
                    tenant.id,
                    database_prefix=self.provisioner.database_prefix,
                    user_prefix=self.provisioner.user_prefix,
                )[1]
            tenant.name = self.name
            tenant.expires_at = self.expires_at
            tenant.provisioning_status = "provisioning"
            tenant.provisioning_error = None
            admins = session.scalars(select(TenantMember).where(
                TenantMember.tenant_id == tenant.id,
                TenantMember.role == "admin",
            ).order_by(TenantMember.id)).all()
            admin = phone_member or (admins[0] if admins else None)
            if admin is None:
                admin = TenantMember(tenant_id=tenant.id, phone=self.phone)
                session.add(admin)
            admin.phone = self.phone
            admin.role = "admin"
            admin.status = "active"
            session.flush()
            tenant_id = tenant.id
        return self._tenant(tenant_id)

    def _tenant(self, tenant_id):
        with self.store.session() as session:
            return session.get(Tenant, tenant_id)

    @staticmethod
    def _present(value):
        return isinstance(value, str) and bool(value.strip())

    def _configure(self, tenant):
        engine = self.registry.get(tenant)
        token = bind_tenant(tenant.id, engine)
        try:
            db.session.remove()
            service = SettingsService(db.session, self.store, tenant.id)
            warehouses = db.session.scalars(select(Warehouse)).all()
            shops = db.session.scalars(select(XianyuShop)).all()
            if len(warehouses) != 1 or len(shops) != 1:
                raise RuntimeError("default binding cardinality is invalid")
            warehouse, shop = warehouses[0], shops[0]
            service.update_warehouse(warehouse.id, {
                "province": self.province,
                "city": self.city,
                "name": "",
            })
            sf_map = {
                "partner_id": "SF_PARTNER_ID",
                "checkword": "SF_CHECKWORD",
                "monthly_card": "SF_MONTHLY_CARD",
                "sender_name": "SF_SENDER_NAME",
                "sender_phone": "SF_SENDER_PHONE",
                "sender_address": "SF_SENDER_ADDRESS",
            }
            sf_payload = {
                field: self.environment[key]
                for field, key in sf_map.items()
                if key in self.environment
            }
            if "SF_TEST_MODE" in self.environment:
                sf_payload["test_mode"] = (
                    self.environment["SF_TEST_MODE"].strip().lower()
                    in {"1", "true", "yes", "on"}
                )
            sf = service.upsert_sf_config(warehouse.id, sf_payload)
            km_map = {
                "app_id": "KUAIMAI_APP_ID",
                "app_secret": "KUAIMAI_APP_SECRET",
                "printer_sn": "KUAIMAI_PRINTER_SN",
            }
            kuaimai = service.upsert_kuaimai_config(warehouse.id, {
                field: self.environment[key]
                for field, key in km_map.items()
                if key in self.environment
            })
            x_payload = {}
            if "XIANYU_APP_KEY" in self.environment:
                x_payload["app_key"] = self.environment["XIANYU_APP_KEY"]
            if "XIANYU_APP_SECRET" in self.environment:
                x_payload["app_secret"] = self.environment["XIANYU_APP_SECRET"]
            x_complete = bool(
                (x_payload.get("app_key", shop.app_key) or "").strip()
                and (
                    self._present(x_payload.get("app_secret"))
                    or shop.app_secret_ciphertext
                )
            )
            x_payload["is_active"] = x_complete
            shop = service.update_xianyu_shop(shop.id, x_payload)
            db.session.commit()
            self.report.tenant_id = tenant.id
            self.report.warehouse_id = warehouse.id
            self.report.shop_id = shop.id
            self.report.sf_config_complete = all((
                sf.partner_id,
                sf.checkword_ciphertext,
                sf.monthly_card_ciphertext,
                sf.sender_name,
                sf.sender_phone,
                sf.sender_address,
            ))
            self.report.kuaimai_config_complete = all((
                kuaimai.app_id,
                kuaimai.app_secret_ciphertext,
                kuaimai.printer_sn,
            ))
            self.report.xianyu_config_complete = x_complete
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()
            reset_tenant(token)

    def verify(self):
        tenant = self._tenant(self.report.tenant_id)
        engine = self.registry.get(tenant)
        with engine.connect() as connection:
            after = self._count_tables(connection, self.report.before_counts)
            issues = dict(self.report.issue_counts)
            issues.update({
                "null_device_warehouses": connection.scalar(text(
                    "SELECT count(*) FROM devices WHERE warehouse_id IS NULL"
                )),
                "null_rental_warehouses": connection.scalar(text(
                    "SELECT count(*) FROM rentals WHERE warehouse_id IS NULL"
                )),
                "null_alert_shops": connection.scalar(text(
                    "SELECT count(*) FROM xianyu_order_alerts "
                    "WHERE xianyu_shop_id IS NULL"
                )),
                "parent_child_warehouse_mismatches": connection.scalar(text(
                    "SELECT count(*) FROM rentals c JOIN rentals p "
                    "ON p.id=c.parent_rental_id WHERE "
                    "c.warehouse_id != p.warehouse_id"
                )),
            })
            head = connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            ))
            warehouse_count = connection.scalar(text(
                "SELECT count(*) FROM warehouses"
            ))
            shop_count = connection.scalar(text(
                "SELECT count(*) FROM xianyu_shops"
            ))
            missing_main_shops = connection.scalar(text(
                "SELECT count(*) FROM rentals WHERE parent_rental_id IS NULL "
                "AND NULLIF(TRIM(xianyu_order_no), '') IS NOT NULL "
                "AND xianyu_shop_id IS NULL"
            ))
            grants = [value.replace("\\_", "_").replace("\\%", "%")
                      for value in connection.exec_driver_sql(
                          "SHOW GRANTS FOR CURRENT_USER"
                      ).scalars()]
            restricted = (
                len(grants) == 2
                and sum(f"ON `{self.database_name}`.*" in g for g in grants) == 1
                and all("GRANT OPTION" not in g for g in grants)
            )
            if self._legacy_sync is not None:
                migrated_sync = connection.execute(text(
                    "SELECT last_success_at, last_error FROM xianyu_shops "
                    "WHERE id=:shop_id"
                ), {"shop_id": self.report.shop_id}).one()
            else:
                migrated_sync = None
        preserved = all(
            after.get(name) == count
            for name, count in self.report.before_counts.items()
            if name not in _SAAS_TABLES
        )
        if not (
            head == CURRENT_HEAD
            and preserved
            and not any(issues.values())
            and warehouse_count == shop_count == 1
            and missing_main_shops == 0
            and restricted
            and migrated_sync == self._legacy_sync
        ):
            raise RuntimeError("default tenant verification failed")
        self.report.head = head
        self.report.after_counts = after
        self.report.issue_counts = issues
        return self.report

    def run(self):
        report = self.preflight()
        if any(report.issue_counts[name] for name in _PREFLIGHT_ISSUES):
            raise MigrationRejected(report)
        try:
            tenant = self._upsert_control()
        except Exception as exc:
            self.logger.error(
                "Default tenant migration failed stage=control type=%s",
                type(exc).__name__,
            )
            raise MigrationFailed("Default tenant migration failed.") from None
        stage = "adoption"
        try:
            self.provisioner.adopt_existing(tenant)
            stage = "configuration"
            tenant = self._tenant(tenant.id)
            self._configure(tenant)
            stage = "verification"
            report = self.verify()
            with self.store.session() as session:
                stored = session.get(Tenant, tenant.id)
                stored.provisioning_status = "active"
                stored.provisioning_error = None
            return report
        except Exception as exc:
            with self.store.session() as session:
                stored = session.get(Tenant, tenant.id)
                stored.provisioning_status = "failed"
                stored.provisioning_error = "Default tenant migration failed."
            self.logger.error(
                "Default tenant migration failed tenant_id=%s stage=%s type=%s",
                tenant.id,
                stage,
                type(exc).__name__,
            )
            raise MigrationFailed("Default tenant migration failed.") from None


def register_default_tenant_command(app):
    app.cli.add_command(migrate_default_tenant)


@click.command("migrate-default-tenant")
@click.option("--name", required=True)
@click.option("--admin-phone", required=True)
@click.option("--expires-at", required=True)
@click.option("--db-name", "database_name", required=True)
@click.option("--province", required=True)
@click.option("--city", required=True)
@click.option("--confirm-maintenance")
@click.option("--confirm-backup")
@with_appcontext
def migrate_default_tenant(**options):
    store = current_app.extensions.get("control_store")
    provisioner = current_app.extensions.get("tenant_provisioner")
    registry = current_app.extensions.get("tenant_engine_registry")
    if store is None or provisioner is None or registry is None:
        raise click.ClickException("Default tenant migration is not configured.")
    try:
        options["expires_at"] = _parse_expiration(options["expires_at"])
        migrator = DefaultTenantMigrator(
            store=store,
            provisioner=provisioner,
            registry=registry,
            logger=current_app.logger,
            **options,
        )
        report = migrator.run()
    except MigrationRejected as exc:
        click.echo(json.dumps(exc.report.to_dict(), sort_keys=True))
        raise click.ClickException("Default tenant preflight failed.") from None
    except Exception:
        raise click.ClickException("Default tenant migration failed.") from None
    click.echo(json.dumps(report.to_dict(), sort_keys=True))
