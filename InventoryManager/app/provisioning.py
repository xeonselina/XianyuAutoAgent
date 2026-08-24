"""Synchronous, idempotent tenant business-database provisioning."""

import io
import logging
import os
import re
import secrets
from contextlib import redirect_stderr, redirect_stdout

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL

from app.auth import normalize_china_phone
from app.control.models import Tenant, TenantMember
from app.crypto import hash_token


LOGGER = logging.getLogger(__name__)
DEFAULT_DATABASE_PREFIX = "inventory_tenant_"
DEFAULT_USER_PREFIX = "im_t"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_]+$")


class TenantPhoneConflict(ValueError):
    """The globally unique member phone already belongs to a tenant."""


class TenantNotFound(LookupError):
    """The requested tenant does not exist in the control database."""


def _validated_identifier(value, maximum_length):
    if (
        not _IDENTIFIER_PATTERN.fullmatch(value)
        or len(value) > maximum_length
    ):
        raise ValueError("unsafe database identifier")
    return value


def format_tenant_identifiers(
    tenant_id,
    database_prefix=DEFAULT_DATABASE_PREFIX,
    user_prefix=DEFAULT_USER_PREFIX,
):
    """Return fixed database/user identifiers after strict validation."""
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("tenant identifier must be a positive integer")
    database_name = f"{database_prefix}{tenant_id:08d}"
    database_username = f"{user_prefix}{tenant_id:08d}"
    return (
        _validated_identifier(database_name, 64),
        _validated_identifier(database_username, 32),
    )


def business_migration_head(migrations_directory):
    """Read the single current business migration head."""
    config = AlembicConfig(
        os.path.join(migrations_directory, "alembic.ini")
    )
    config.set_main_option("script_location", migrations_directory)
    return ScriptDirectory.from_config(config).get_current_head()


def run_business_migrations(database_url, migrations_directory):
    """Upgrade one tenant using a minimal temporary Flask migration app."""
    migration_app = Flask("tenant_business_migration")
    migration_app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    migration_db = SQLAlchemy()
    migration = Migrate()
    migration_db.init_app(migration_app)
    migration.init_app(
        migration_app,
        migration_db,
        directory=migrations_directory,
    )
    with migration_app.app_context():
        alembic_logger = logging.getLogger("alembic")
        previous_level = alembic_logger.level
        try:
            alembic_config = migration.get_config(migrations_directory)
            alembic_config.attributes["programmatic_provisioning"] = True
            alembic_logger.setLevel(logging.CRITICAL + 1)
            with redirect_stdout(io.StringIO()), redirect_stderr(
                io.StringIO()
            ):
                alembic_command.upgrade(alembic_config, "head")
        finally:
            alembic_logger.setLevel(previous_level)
            migration_db.session.remove()
            migration_db.engine.dispose()


class TenantProvisioner:
    """Create and migrate immutable per-tenant database credentials."""

    def __init__(
        self,
        store,
        provisioner_database_url,
        migrations_directory,
        tenant_db_host,
        tenant_db_port,
        database_prefix=DEFAULT_DATABASE_PREFIX,
        user_prefix=DEFAULT_USER_PREFIX,
        logger=None,
    ):
        self.store = store
        self.migrations_directory = migrations_directory
        self.tenant_db_host = tenant_db_host
        self.tenant_db_port = int(tenant_db_port)
        self.database_prefix = database_prefix
        self.user_prefix = user_prefix
        self.logger = logger or LOGGER
        format_tenant_identifiers(
            1,
            database_prefix=database_prefix,
            user_prefix=user_prefix,
        )
        self.engine = create_engine(
            provisioner_database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

    def create(self, name, admin_phone, expires_at):
        normalized_name = self._normalize_name(name)
        normalized_phone = normalize_china_phone(admin_phone)
        if not hasattr(expires_at, "isoformat"):
            raise ValueError("expires_at must be a datetime")

        raw_password = secrets.token_urlsafe(32)
        encrypted_password = self.store.secret_box.encrypt(
            raw_password,
            purpose="tenant-db-password",
        )
        lock_name = f"tenant-phone-{hash_token(normalized_phone)[:48]}"
        with self.store.locked_session((lock_name,), timeout=5) as session:
            existing_member = session.scalar(
                select(TenantMember).where(
                    TenantMember.phone == normalized_phone
                )
            )
            if existing_member is not None:
                raise TenantPhoneConflict(normalized_phone)

            placeholder = secrets.token_hex(12)
            tenant = Tenant(
                name=normalized_name,
                status="active",
                expires_at=expires_at,
                db_name=f"pending_{placeholder}",
                db_username=f"pending_{placeholder}"[:32],
                db_password_ciphertext=encrypted_password,
                provisioning_status="provisioning",
                provisioning_error=None,
            )
            session.add(tenant)
            session.flush()
            database_name, database_username = format_tenant_identifiers(
                tenant.id,
                database_prefix=self.database_prefix,
                user_prefix=self.user_prefix,
            )
            tenant.db_name = database_name
            tenant.db_username = database_username
            session.add(
                TenantMember(
                    tenant_id=tenant.id,
                    phone=normalized_phone,
                    role="admin",
                    status="active",
                )
            )
            tenant_id = tenant.id

        return self._provision(tenant_id)

    def retry(self, tenant_id):
        with self.store.session() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                raise TenantNotFound(tenant_id)
            tenant.provisioning_status = "provisioning"
            tenant.provisioning_error = None
        return self._provision(tenant_id)

    def upgrade(self, tenant):
        database_url = self._tenant_database_url(tenant)
        run_business_migrations(
            database_url,
            self.migrations_directory,
        )
        return business_migration_head(self.migrations_directory)

    def dispose(self):
        self.engine.dispose()

    def _provision(self, tenant_id):
        tenant = self._get_tenant(tenant_id)
        try:
            self._ensure_database_and_user(tenant)
        except Exception as exc:
            self._record_failure(
                tenant_id,
                "Business database setup failed.",
                "database setup",
                exc,
            )
            return self._get_tenant(tenant_id)

        tenant = self._get_tenant(tenant_id)
        try:
            self.upgrade(tenant)
        except Exception as exc:
            self._record_failure(
                tenant_id,
                "Business database migration failed.",
                "migration",
                exc,
            )
            return self._get_tenant(tenant_id)

        with self.store.session() as session:
            tenant = session.get(Tenant, tenant_id)
            tenant.provisioning_status = "active"
            tenant.provisioning_error = None
        return self._get_tenant(tenant_id)

    def _ensure_database_and_user(self, tenant):
        database_name = _validated_identifier(tenant.db_name, 64)
        database_username = _validated_identifier(
            tenant.db_username,
            32,
        )
        password = self.store.secret_box.decrypt(
            tenant.db_password_ciphertext,
            purpose="tenant-db-password",
        )
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            connection.execute(
                text(
                    f"CREATE USER IF NOT EXISTS "
                    f"`{database_username}`@'%' "
                    "IDENTIFIED BY :password"
                ),
                {"password": password},
            )
            connection.execute(
                text(
                    f"ALTER USER `{database_username}`@'%' "
                    "IDENTIFIED BY :password"
                ),
                {"password": password},
            )
            connection.execute(
                text(
                    f"GRANT ALL PRIVILEGES ON `{database_name}`.* "
                    f"TO `{database_username}`@'%'"
                )
            )

    def _tenant_database_url(self, tenant):
        database_name = _validated_identifier(tenant.db_name, 64)
        database_username = _validated_identifier(
            tenant.db_username,
            32,
        )
        password = self.store.secret_box.decrypt(
            tenant.db_password_ciphertext,
            purpose="tenant-db-password",
        )
        return URL.create(
            "mysql+pymysql",
            username=database_username,
            password=password,
            host=self.tenant_db_host,
            port=self.tenant_db_port,
            database=database_name,
        ).render_as_string(hide_password=False)

    def _get_tenant(self, tenant_id):
        with self.store.session() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                raise TenantNotFound(tenant_id)
            return tenant

    def _record_failure(self, tenant_id, summary, stage, exception):
        with self.store.session() as session:
            tenant = session.get(Tenant, tenant_id)
            tenant.provisioning_status = "failed"
            tenant.provisioning_error = summary[:160]
        self.logger.error(
            "Tenant provisioning failed tenant_id=%s stage=%s type=%s",
            tenant_id,
            stage,
            type(exception).__name__,
        )

    @staticmethod
    def _normalize_name(name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tenant name is required")
        normalized = name.strip()
        if len(normalized) > 128:
            raise ValueError("tenant name is too long")
        return normalized
