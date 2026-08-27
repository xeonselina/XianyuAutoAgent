#!/usr/bin/env python3
"""Prepare and serve the isolated mobile real-backend E2E fixture."""

from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy.engine import URL


_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9_]+$")


def validate_e2e_identifier(identifier: str) -> str:
    """Reject every database/user identifier outside the E2E namespace."""
    if (
        not isinstance(identifier, str)
        or "e2e_test" not in identifier
        or not _SAFE_IDENTIFIER.fullmatch(identifier)
        or len(identifier) > 64
    ):
        raise ValueError("database identifiers must be safe e2e_test names")
    return identifier


def build_database_url(
    *,
    username: str,
    password: str,
    host: str,
    port: int,
    database: str,
) -> URL:
    validate_e2e_identifier(database)
    validate_e2e_identifier(username)
    return URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
    )


def select_fixture_warehouse(warehouses):
    """Reuse the single warehouse created by the business migrations."""
    if len(warehouses) != 1:
        raise RuntimeError(
            "mobile E2E requires exactly one migrated warehouse"
        )
    warehouse = warehouses[0]
    warehouse.province = "广东省"
    warehouse.city = "深圳市"
    warehouse.name = "E2E 测试仓"
    return warehouse


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _settings() -> dict[str, object]:
    host = os.environ.get("E2E_DB_HOST", "e2e-db")
    port = int(os.environ.get("E2E_DB_PORT", "3306"))
    control_database = validate_e2e_identifier(
        os.environ.get(
            "E2E_CONTROL_DATABASE", "xianyu_mobile_e2e_test_control"
        )
    )
    tenant_database = validate_e2e_identifier(
        os.environ.get(
            "E2E_TENANT_DATABASE", "xianyu_mobile_e2e_test_tenant"
        )
    )
    tenant_user = validate_e2e_identifier(
        os.environ.get(
            "E2E_TENANT_USER", "xianyu_mobile_e2e_test_user"
        )
    )
    tenant_password = _required("E2E_TENANT_PASSWORD")
    root_password = os.environ.get("E2E_DB_ROOT_PASSWORD")
    master_key = _required("SAAS_MASTER_KEY")

    return {
        "host": host,
        "port": port,
        "control_database": control_database,
        "tenant_database": tenant_database,
        "tenant_user": tenant_user,
        "tenant_password": tenant_password,
        "master_key": master_key,
        "secret_key": _required("SECRET_KEY"),
        "sms_code": os.environ.get("E2E_SMS_CODE", "246810"),
        "root_password": root_password,
        "control_url": build_database_url(
            username=tenant_user,
            password=tenant_password,
            host=host,
            port=port,
            database=control_database,
        ),
        "tenant_url": build_database_url(
            username=tenant_user,
            password=tenant_password,
            host=host,
            port=port,
            database=tenant_database,
        ),
    }


def _root_url(settings: dict[str, object]) -> URL:
    password = settings["root_password"]
    if not password:
        raise RuntimeError("E2E_DB_ROOT_PASSWORD is required for prepare")
    return URL.create(
        "mysql+pymysql",
        username="root",
        password=str(password),
        host=str(settings["host"]),
        port=int(settings["port"]),
        database="mysql",
    )


def _create_databases_and_user(settings: dict[str, object]) -> None:
    from sqlalchemy import create_engine, text

    control_database = str(settings["control_database"])
    tenant_database = str(settings["tenant_database"])
    tenant_user = str(settings["tenant_user"])
    tenant_password = str(settings["tenant_password"])
    engine = create_engine(_root_url(settings), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for database in (control_database, tenant_database):
                connection.execute(text(
                    f"CREATE DATABASE `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                ))
            connection.execute(
                text(
                    f"CREATE USER '{tenant_user}'@'%' "
                    "IDENTIFIED BY :password"
                ),
                {"password": tenant_password},
            )
            for database in (control_database, tenant_database):
                connection.execute(text(
                    f"GRANT ALL PRIVILEGES ON `{database}`.* "
                    f"TO '{tenant_user}'@'%'"
                ))
    finally:
        engine.dispose()


def _run_migrations(settings: dict[str, object]) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from app.provisioning import run_business_migrations

    control_url = settings["control_url"].render_as_string(
        hide_password=False
    )
    tenant_url = settings["tenant_url"].render_as_string(
        hide_password=False
    )
    os.environ["CONTROL_DATABASE_URL"] = control_url
    control_config = AlembicConfig("/app/control_alembic.ini")
    command.upgrade(control_config, "head")
    run_business_migrations(tenant_url, "/app/migrations")


def _seed_control(settings: dict[str, object]) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.control.models import Tenant, TenantMember
    from app.crypto import SecretBox

    engine = create_engine(settings["control_url"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            tenant = Tenant(
                name="Mobile E2E Tenant",
                status="active",
                expires_at=datetime.utcnow() + timedelta(days=30),
                db_name=str(settings["tenant_database"]),
                db_username=str(settings["tenant_user"]),
                db_password_ciphertext=SecretBox.from_base64(
                    str(settings["master_key"])
                ).encrypt(
                    str(settings["tenant_password"]),
                    purpose="tenant-db-password",
                ),
                provisioning_status="active",
            )
            session.add(tenant)
            session.flush()
            session.add(TenantMember(
                tenant_id=tenant.id,
                phone="+8613800138000",
                role="admin",
                status="active",
            ))
    finally:
        engine.dispose()


def _seed_business(settings: dict[str, object]) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models import (
        Device,
        DeviceModel,
        Rental,
        RentalRelayBinding,
        RentalRelayCase,
        Warehouse,
    )

    engine = create_engine(settings["tenant_url"], pool_pre_ping=True)
    today = date.today()
    try:
        with Session(engine) as session, session.begin():
            warehouse = select_fixture_warehouse(
                session.scalars(
                    select(Warehouse).order_by(Warehouse.id)
                ).all()
            )
            main_model = session.scalar(select(DeviceModel).where(
                DeviceModel.name == "x200u"
            ))
            if main_model is None:
                raise RuntimeError("business migration did not seed x200u")
            second_model = DeviceModel(
                name="x300u",
                display_name="VIVO X300 Ultra",
                is_active=True,
                is_accessory=False,
            )
            phone_model = DeviceModel(
                name="phone_holder",
                display_name="手机支架",
                is_active=True,
                is_accessory=True,
                parent_model=main_model,
            )
            tripod_model = DeviceModel(
                name="tripod",
                display_name="三脚架",
                is_active=True,
                is_accessory=True,
                parent_model=main_model,
            )
            session.add_all([
                second_model,
                phone_model,
                tripod_model,
            ])
            session.flush()

            relay_device = Device(
                name="E2E 主设备 1001",
                serial_number="E2E-MAIN-1001",
                model=main_model.name,
                model_id=main_model.id,
                is_accessory=False,
                warehouse_id=warehouse.id,
                lifecycle_status="active",
            )
            available_device = Device(
                name="E2E 主设备 2001",
                serial_number="E2E-MAIN-2001",
                model=second_model.name,
                model_id=second_model.id,
                is_accessory=False,
                warehouse_id=warehouse.id,
                lifecycle_status="active",
            )
            phone_holder = Device(
                name="手机支架 E2E-01",
                serial_number="E2E-PHONE-HOLDER-01",
                model=phone_model.name,
                model_id=phone_model.id,
                is_accessory=True,
                warehouse_id=warehouse.id,
                lifecycle_status="active",
            )
            tripod = Device(
                name="三脚架 E2E-01",
                serial_number="E2E-TRIPOD-01",
                model=tripod_model.name,
                model_id=tripod_model.id,
                is_accessory=True,
                warehouse_id=warehouse.id,
                lifecycle_status="active",
            )
            sold_device = Device(
                name="E2E 已售设备 3001",
                serial_number="E2E-SOLD-3001",
                model=main_model.name,
                model_id=main_model.id,
                is_accessory=False,
                warehouse_id=warehouse.id,
                lifecycle_status="sold",
                lifecycle_reason="E2E fixture",
                lifecycle_date=datetime.utcnow(),
            )
            session.add_all([
                relay_device,
                available_device,
                phone_holder,
                tripod,
                sold_device,
            ])
            session.flush()

            predecessor = Rental(
                device_id=relay_device.id,
                warehouse_id=warehouse.id,
                start_date=today - timedelta(days=4),
                end_date=today - timedelta(days=1),
                ship_out_time=datetime.combine(
                    today - timedelta(days=5), time(19)
                ),
                ship_in_time=datetime.combine(
                    today + timedelta(days=3), time(12)
                ),
                customer_name="前单客户 1001",
                customer_phone="13811112222",
                destination="广东省深圳市南山区一号路",
                buyer_id="E2E买家1",
                status="shipped",
            )
            successor = Rental(
                device_id=relay_device.id,
                warehouse_id=warehouse.id,
                start_date=today + timedelta(days=4),
                end_date=today + timedelta(days=8),
                ship_out_time=datetime.combine(
                    today + timedelta(days=1), time(19)
                ),
                ship_in_time=datetime.combine(
                    today + timedelta(days=10), time(12)
                ),
                customer_name="后单客户 1002",
                customer_phone="13933334444",
                destination="上海市浦东新区二号路",
                buyer_id="E2E买家2",
                status="not_shipped",
            )
            completed = Rental(
                device_id=available_device.id,
                warehouse_id=warehouse.id,
                start_date=today - timedelta(days=20),
                end_date=today - timedelta(days=15),
                ship_out_time=datetime.combine(
                    today - timedelta(days=21), time(19)
                ),
                ship_in_time=datetime.combine(
                    today - timedelta(days=14), time(12)
                ),
                customer_name="完成客户 1003",
                customer_phone="13755556666",
                destination="北京市朝阳区三号路",
                buyer_id="E2E买家3",
                status="completed",
            )
            session.add_all([predecessor, successor, completed])
            session.flush()
            session.add_all([
                RentalRelayCase(
                    predecessor_rental_id=predecessor.id,
                    successor_rental_id=successor.id,
                    status="shipped",
                    sf_tracking_number="SF1234567890",
                    sf_tracking_status="in_transit",
                    sf_tracking_summary="E2E 运送中",
                    shipped_at=datetime.utcnow(),
                ),
                RentalRelayBinding(
                    predecessor_rental_id=predecessor.id,
                    successor_rental_id=successor.id,
                ),
            ])
    finally:
        engine.dispose()


def _verify_restricted_grants(settings: dict[str, object]) -> None:
    from sqlalchemy import create_engine, text

    expected = {
        str(settings["control_database"]),
        str(settings["tenant_database"]),
    }
    engine = create_engine(_root_url(settings), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(
                f"SHOW GRANTS FOR '{settings['tenant_user']}'@'%'"
            )).scalars().all()
    finally:
        engine.dispose()
    grants = "\n".join(rows)
    for database in expected:
        if f"`{database}`.*" not in grants:
            raise RuntimeError(f"missing isolated grant for {database}")
    forbidden = ("inventory_management", "`mysql`.*", "`*`.*")
    if any(value in grants for value in forbidden):
        raise RuntimeError("E2E user has a non-isolated database grant")


def prepare() -> None:
    settings = _settings()
    _create_databases_and_user(settings)
    _run_migrations(settings)
    _seed_control(settings)
    _seed_business(settings)
    _verify_restricted_grants(settings)
    print("prepared isolated mobile E2E databases")


def serve() -> None:
    settings = _settings()
    os.environ["TESTING"] = "true"

    from app import create_app
    from config import TestingConfig

    class MobileE2EConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        IS_PRODUCTION = False
        CONTROL_DATABASE_URL = settings["control_url"].render_as_string(
            hide_password=False
        )
        SQLALCHEMY_DATABASE_URI = settings["tenant_url"].render_as_string(
            hide_password=False
        )
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
        SAAS_MASTER_KEY = settings["master_key"]
        SECRET_KEY = settings["secret_key"]
        DEV_SMS_CODE = settings["sms_code"]
        SMS_SENDER = None
        PROVISIONER_DATABASE_URL = None
        TENANT_DB_HOST = settings["host"]
        TENANT_DB_PORT = settings["port"]
        CORS_ORIGINS = []
        SESSION_COOKIE_SECURE = False

    app = create_app(MobileE2EConfig)
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve"))
    args = parser.parse_args()
    {"prepare": prepare, "serve": serve}[args.command]()


if __name__ == "__main__":
    main()
