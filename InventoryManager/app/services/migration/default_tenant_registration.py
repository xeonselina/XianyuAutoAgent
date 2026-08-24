"""Idempotent in-place registration for the existing default-tenant schema.

The tenant and control databases cannot share one transaction.  The first
operation writes/replays the single identity row in an already selected tenant
schema.  The second operation consumes that immutable result and writes/replays
the control-plane tenant, first unverified Admin, membership, trusted route and
control-side identity record in one caller-owned control transaction.

Neither operation selects a database, commits, copies business data, accepts a
password/DSN/provider secret, renames a schema, or adds tenant IDs to business
tables.  A crash between the two operations is recovered by replaying the same
manifest and controlled identity inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Final
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.database_identity import TenantDatabaseIdentity
from inventory_control.default_migration import (
    DefaultTenantIdentityInputs,
    DefaultTenantMigrationManifest,
    require_default_tenant_identity_inputs_match,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
    TenantMembership,
    User,
)


_DIGEST_BYTES: Final = 32
_ROUTE_TOKEN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}")
_ADMIN_USER_DOMAIN: Final = "inventory-manager/default-admin-user/v1/"
_ADMIN_MEMBERSHIP_DOMAIN: Final = (
    "inventory-manager/default-admin-membership/v1/"
)
_MIGRATION_SOURCE_DOMAIN: Final = "inventory-manager/default-migration-source/v1/"
_ACTIVATION_DOMAIN: Final = "inventory-manager/default-route-activation/v1/"


class DefaultTenantRegistrationError(RuntimeError):
    code = "DEFAULT_TENANT_REGISTRATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultTenantRegistrationInputError(DefaultTenantRegistrationError):
    code = "DEFAULT_TENANT_REGISTRATION_INPUT_INVALID"


class DefaultTenantRegistrationTransactionError(DefaultTenantRegistrationError):
    code = "DEFAULT_TENANT_REGISTRATION_TRANSACTION_INVALID"


class DefaultTenantRegistrationConflictError(DefaultTenantRegistrationError):
    code = "DEFAULT_TENANT_REGISTRATION_CONFLICT"


class DefaultTenantRegistrationPersistenceError(DefaultTenantRegistrationError):
    code = "DEFAULT_TENANT_REGISTRATION_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultTenantRouteRegistration:
    """Non-secret, versioned route metadata created outside this service."""

    database_instance_key: str
    schema_generation: int
    schema_digest: bytes
    dml_username: str
    dml_credential_generation: int
    dml_root_key_version: int
    dml_derivation_version: int
    platform_read_username: str
    platform_read_credential_generation: int
    platform_read_root_key_version: int
    platform_read_derivation_version: int

    def __post_init__(self) -> None:
        for value in (
            self.database_instance_key,
            self.dml_username,
            self.platform_read_username,
        ):
            if not isinstance(value, str) or _ROUTE_TOKEN.fullmatch(value) is None:
                raise DefaultTenantRegistrationInputError()
        if self.dml_username == self.platform_read_username:
            raise DefaultTenantRegistrationInputError()
        for value in (
            self.schema_generation,
            self.dml_credential_generation,
            self.dml_root_key_version,
            self.dml_derivation_version,
            self.platform_read_credential_generation,
            self.platform_read_root_key_version,
            self.platform_read_derivation_version,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise DefaultTenantRegistrationInputError()
        if not isinstance(self.schema_digest, bytes) or len(
            self.schema_digest
        ) != _DIGEST_BYTES:
            raise DefaultTenantRegistrationInputError()


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultTenantDatabaseIdentityResult:
    manifest_digest: bytes
    tenant_uuid: UUID
    database_uuid: UUID
    schema_generation: int
    identity_created_at: datetime
    created: bool

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_digest, bytes) or len(
            self.manifest_digest
        ) != _DIGEST_BYTES:
            raise DefaultTenantRegistrationInputError()
        if (
            not isinstance(self.tenant_uuid, UUID)
            or not isinstance(self.database_uuid, UUID)
            or self.tenant_uuid == self.database_uuid
            or isinstance(self.schema_generation, bool)
            or not isinstance(self.schema_generation, int)
            or self.schema_generation < 1
            or not isinstance(self.created, bool)
        ):
            raise DefaultTenantRegistrationInputError()
        object.__setattr__(
            self,
            "identity_created_at",
            _as_utc(self.identity_created_at),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultTenantControlRegistrationResult:
    tenant_uuid: UUID
    database_uuid: UUID
    admin_user_uuid: UUID
    admin_membership_uuid: UUID
    route_version: int
    created: bool


class DefaultTenantInPlaceRegistrationService:
    """Register one existing schema without copying or sharing its tables."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        if clock is not None and not callable(clock):
            raise TypeError("clock is invalid")
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def write_tenant_database_identity(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        schema_generation: int,
    ) -> DefaultTenantDatabaseIdentityResult:
        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise DefaultTenantRegistrationInputError()
        generation = _positive(schema_generation)
        _require_explicit_transaction(session)
        try:
            identities = tuple(
                session.scalars(
                    sa.select(TenantDatabaseIdentity)
                    .order_by(TenantDatabaseIdentity.singleton_key)
                    .with_for_update()
                    .execution_options(autoflush=False, populate_existing=True)
                )
            )
            if len(identities) > 1:
                raise DefaultTenantRegistrationConflictError()
            created = not identities
            if created:
                now = _as_utc(self._clock())
                identity = TenantDatabaseIdentity(
                    singleton_key=1,
                    tenant_id=str(manifest.tenant_uuid),
                    database_uuid=str(manifest.database_uuid),
                    schema_generation=generation,
                    created_at=now.replace(tzinfo=None),
                )
                with session.begin_nested():
                    session.add(identity)
                    session.flush()
                    session.refresh(identity)
            else:
                identity = identities[0]
                _require_tenant_identity(
                    identity,
                    manifest=manifest,
                    schema_generation=generation,
                )
            created_at = _as_utc(identity.created_at)
        except DefaultTenantRegistrationError:
            raise
        except IntegrityError:
            raise DefaultTenantRegistrationConflictError() from None
        except SQLAlchemyError:
            raise DefaultTenantRegistrationPersistenceError() from None
        return DefaultTenantDatabaseIdentityResult(
            manifest_digest=manifest.digest,
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            schema_generation=generation,
            identity_created_at=created_at,
            created=created,
        )

    def write_control_registration(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        identity_inputs: DefaultTenantIdentityInputs,
        tenant_identity: DefaultTenantDatabaseIdentityResult,
        route: DefaultTenantRouteRegistration,
    ) -> DefaultTenantControlRegistrationResult:
        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise DefaultTenantRegistrationInputError()
        try:
            require_default_tenant_identity_inputs_match(manifest, identity_inputs)
        except (TypeError, ValueError):
            raise DefaultTenantRegistrationInputError() from None
        if (
            not isinstance(tenant_identity, DefaultTenantDatabaseIdentityResult)
            or tenant_identity.manifest_digest != manifest.digest
            or tenant_identity.tenant_uuid != manifest.tenant_uuid
            or tenant_identity.database_uuid != manifest.database_uuid
            or not isinstance(route, DefaultTenantRouteRegistration)
            or tenant_identity.schema_generation != route.schema_generation
        ):
            raise DefaultTenantRegistrationInputError()
        _require_explicit_transaction(session)

        admin_uuid = _derived_uuid(
            manifest.tenant_uuid,
            _ADMIN_USER_DOMAIN,
            manifest.migration_idempotency_key,
        )
        membership_uuid = _derived_uuid(
            manifest.tenant_uuid,
            _ADMIN_MEMBERSHIP_DOMAIN,
            manifest.migration_idempotency_key,
        )
        source_uuid = _derived_uuid(
            manifest.tenant_uuid,
            _MIGRATION_SOURCE_DOMAIN,
            manifest.migration_idempotency_key,
        )
        activation_uuid = _derived_uuid(
            manifest.tenant_uuid,
            _ACTIVATION_DOMAIN,
            manifest.migration_idempotency_key,
        )
        try:
            existing = _lock_control_identity(
                session,
                manifest=manifest,
                admin_uuid=admin_uuid,
                membership_uuid=membership_uuid,
                canonical_phone=identity_inputs.first_admin_phone_e164,
                route=route,
            )
            if existing is None:
                with session.begin_nested():
                    tenant = Tenant(
                        id=str(manifest.tenant_uuid),
                        name=identity_inputs.display_name,
                        status="provisioning",
                        timezone="Asia/Shanghai",
                        locale="zh-CN",
                    )
                    user = User(
                        id=str(admin_uuid),
                        phone_region_iso2="CN",
                        phone_e164=identity_inputs.first_admin_phone_e164,
                        phone_normalization_version=PHONE_NORMALIZATION_VERSION,
                        phone_metadata_version=CN_MOBILE_METADATA_VERSION,
                        phone_verified_at=None,
                        status="unverified",
                        auth_version=1,
                    )
                    session.add_all((tenant, user))
                    session.flush()
                    database_route = TenantDatabase(
                        tenant_id=str(manifest.tenant_uuid),
                        database_uuid=str(manifest.database_uuid),
                        database_instance_key=route.database_instance_key,
                        database_name=manifest.source_schema_name,
                        status="provisional",
                        schema_version=manifest.tenant_schema_head,
                        activated_by_registration_commit_uuid=str(activation_uuid),
                        activation_route_version=1,
                        activation_credential_generation=(
                            route.dml_credential_generation
                        ),
                        dml_username=route.dml_username,
                        dml_credential_generation=route.dml_credential_generation,
                        dml_root_key_version=route.dml_root_key_version,
                        dml_derivation_version=route.dml_derivation_version,
                        route_version=1,
                        dml_desired_login_state="active",
                        dml_observed_login_state="active",
                        dml_login_state_version=1,
                        platform_read_username=route.platform_read_username,
                        platform_read_credential_generation=(
                            route.platform_read_credential_generation
                        ),
                        platform_read_root_key_version=(
                            route.platform_read_root_key_version
                        ),
                        platform_read_derivation_version=(
                            route.platform_read_derivation_version
                        ),
                        platform_read_route_version=1,
                    )
                    membership = TenantMembership(
                        id=str(membership_uuid),
                        tenant_id=str(manifest.tenant_uuid),
                        user_id=str(admin_uuid),
                        role_key="admin",
                        status="active",
                        source_type="migration",
                        source_uuid=str(source_uuid),
                        registration_commit_uuid=None,
                        row_version=1,
                    )
                    session.add_all((database_route, membership))
                    session.flush()
                    session.add(
                        DatabaseIdentityControlRecord(
                            tenant_id=str(manifest.tenant_uuid),
                            database_uuid=str(manifest.database_uuid),
                            expected_schema_generation=route.schema_generation,
                            observed_schema_generation=route.schema_generation,
                            expected_schema_revision=manifest.tenant_schema_head,
                            expected_schema_sha256=route.schema_digest,
                            observed_schema_revision=manifest.tenant_schema_head,
                            observed_schema_sha256=route.schema_digest,
                            row_version=1,
                            identity_created_at=(
                                tenant_identity.identity_created_at
                            ),
                            last_verified_at=_as_utc(self._clock()),
                        )
                    )
                    session.flush()
                created = True
            else:
                _require_existing_control_identity(
                    existing,
                    manifest=manifest,
                    inputs=identity_inputs,
                    tenant_identity=tenant_identity,
                    route=route,
                    admin_uuid=admin_uuid,
                    membership_uuid=membership_uuid,
                    source_uuid=source_uuid,
                    activation_uuid=activation_uuid,
                )
                created = False
        except DefaultTenantRegistrationError:
            raise
        except IntegrityError:
            raise DefaultTenantRegistrationConflictError() from None
        except SQLAlchemyError:
            raise DefaultTenantRegistrationPersistenceError() from None

        return DefaultTenantControlRegistrationResult(
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            admin_user_uuid=admin_uuid,
            admin_membership_uuid=membership_uuid,
            route_version=1,
            created=created,
        )


@dataclass(frozen=True, slots=True)
class _ExistingControlIdentity:
    tenant: Tenant | None
    user: User | None
    membership: TenantMembership | None
    route: TenantDatabase | None
    identity: DatabaseIdentityControlRecord | None


def _lock_control_identity(
    session: Session,
    *,
    manifest: DefaultTenantMigrationManifest,
    admin_uuid: UUID,
    membership_uuid: UUID,
    canonical_phone: str,
    route: DefaultTenantRouteRegistration,
) -> _ExistingControlIdentity | None:
    tenants = tuple(
        session.scalars(
            sa.select(Tenant)
            .where(Tenant.id == str(manifest.tenant_uuid))
            .with_for_update()
        )
    )
    users = tuple(
        session.scalars(
            sa.select(User)
            .where(
                sa.or_(
                    User.id == str(admin_uuid),
                    User.phone_e164 == canonical_phone,
                )
            )
            .with_for_update()
        )
    )
    memberships = tuple(
        session.scalars(
            sa.select(TenantMembership)
            .where(
                sa.or_(
                    TenantMembership.id == str(membership_uuid),
                    TenantMembership.tenant_id == str(manifest.tenant_uuid),
                    TenantMembership.user_id == str(admin_uuid),
                )
            )
            .with_for_update()
        )
    )
    routes = tuple(
        session.scalars(
            sa.select(TenantDatabase)
            .where(
                sa.or_(
                    TenantDatabase.tenant_id == str(manifest.tenant_uuid),
                    TenantDatabase.database_uuid == str(manifest.database_uuid),
                    sa.and_(
                        TenantDatabase.database_instance_key
                        == route.database_instance_key,
                        TenantDatabase.database_name == manifest.source_schema_name,
                    ),
                )
            )
            .with_for_update()
        )
    )
    identities = tuple(
        session.scalars(
            sa.select(DatabaseIdentityControlRecord)
            .where(
                sa.or_(
                    DatabaseIdentityControlRecord.tenant_id
                    == str(manifest.tenant_uuid),
                    DatabaseIdentityControlRecord.database_uuid
                    == str(manifest.database_uuid),
                )
            )
            .with_for_update()
        )
    )
    groups = (tenants, users, memberships, routes, identities)
    if any(len(items) > 1 for items in groups):
        raise DefaultTenantRegistrationConflictError()
    if all(not items for items in groups):
        return None
    if any(not items for items in groups):
        raise DefaultTenantRegistrationConflictError()
    return _ExistingControlIdentity(
        tenant=tenants[0],
        user=users[0],
        membership=memberships[0],
        route=routes[0],
        identity=identities[0],
    )


def _require_existing_control_identity(
    existing: _ExistingControlIdentity,
    *,
    manifest: DefaultTenantMigrationManifest,
    inputs: DefaultTenantIdentityInputs,
    tenant_identity: DefaultTenantDatabaseIdentityResult,
    route: DefaultTenantRouteRegistration,
    admin_uuid: UUID,
    membership_uuid: UUID,
    source_uuid: UUID,
    activation_uuid: UUID,
) -> None:
    tenant = existing.tenant
    user = existing.user
    membership = existing.membership
    database_route = existing.route
    identity = existing.identity
    assert tenant is not None
    assert user is not None
    assert membership is not None
    assert database_route is not None
    assert identity is not None
    if (
        tenant.id != str(manifest.tenant_uuid)
        or tenant.name != inputs.display_name
        or tenant.status not in {"provisioning", "active"}
        or tenant.timezone != "Asia/Shanghai"
        or tenant.locale != "zh-CN"
        or user.id != str(admin_uuid)
        or user.phone_region_iso2 != "CN"
        or user.phone_e164 != inputs.first_admin_phone_e164
        or user.phone_normalization_version != PHONE_NORMALIZATION_VERSION
        or user.phone_metadata_version != CN_MOBILE_METADATA_VERSION
        or user.status not in {"unverified", "active"}
        or membership.id != str(membership_uuid)
        or membership.tenant_id != str(manifest.tenant_uuid)
        or membership.user_id != str(admin_uuid)
        or membership.role_key != "admin"
        or membership.status != "active"
        or membership.source_type != "migration"
        or membership.source_uuid != str(source_uuid)
        or membership.registration_commit_uuid is not None
        or database_route.tenant_id != str(manifest.tenant_uuid)
        or database_route.database_uuid != str(manifest.database_uuid)
        or database_route.database_instance_key != route.database_instance_key
        or database_route.database_name != manifest.source_schema_name
        or database_route.status != "provisional"
        or database_route.schema_version != manifest.tenant_schema_head
        or database_route.activated_by_registration_commit_uuid
        != str(activation_uuid)
        or database_route.activation_route_version != 1
        or database_route.activation_credential_generation
        != route.dml_credential_generation
        or database_route.dml_username != route.dml_username
        or database_route.dml_credential_generation
        != route.dml_credential_generation
        or database_route.dml_root_key_version != route.dml_root_key_version
        or database_route.dml_derivation_version != route.dml_derivation_version
        or database_route.route_version != 1
        or database_route.dml_desired_login_state != "active"
        or database_route.dml_observed_login_state != "active"
        or database_route.dml_login_state_version != 1
        or database_route.platform_read_username != route.platform_read_username
        or database_route.platform_read_credential_generation
        != route.platform_read_credential_generation
        or database_route.platform_read_root_key_version
        != route.platform_read_root_key_version
        or database_route.platform_read_derivation_version
        != route.platform_read_derivation_version
        or database_route.platform_read_route_version != 1
        or identity.tenant_id != str(manifest.tenant_uuid)
        or identity.database_uuid != str(manifest.database_uuid)
        or identity.expected_schema_generation != route.schema_generation
        or identity.observed_schema_generation != route.schema_generation
        or identity.expected_schema_revision != manifest.tenant_schema_head
        or identity.observed_schema_revision != manifest.tenant_schema_head
        or identity.expected_schema_sha256 != route.schema_digest
        or identity.observed_schema_sha256 != route.schema_digest
        or _as_utc(identity.identity_created_at)
        != tenant_identity.identity_created_at
    ):
        raise DefaultTenantRegistrationConflictError()


def _require_tenant_identity(
    identity: TenantDatabaseIdentity,
    *,
    manifest: DefaultTenantMigrationManifest,
    schema_generation: int,
) -> None:
    try:
        tenant_uuid = UUID(identity.tenant_id)
        database_uuid = UUID(identity.database_uuid)
    except (AttributeError, TypeError, ValueError):
        raise DefaultTenantRegistrationConflictError() from None
    if (
        identity.singleton_key != 1
        or tenant_uuid != manifest.tenant_uuid
        or database_uuid != manifest.database_uuid
        or str(tenant_uuid) != identity.tenant_id
        or str(database_uuid) != identity.database_uuid
        or identity.schema_generation != schema_generation
        or identity.created_at is None
    ):
        raise DefaultTenantRegistrationConflictError()


def _require_explicit_transaction(session: Session) -> None:
    if not isinstance(session, Session):
        raise DefaultTenantRegistrationTransactionError()
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise DefaultTenantRegistrationTransactionError()


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DefaultTenantRegistrationInputError()
    return value


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise DefaultTenantRegistrationInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if value.utcoffset() is None:
        raise DefaultTenantRegistrationInputError()
    return value.astimezone(timezone.utc)


def _derived_uuid(namespace: UUID, domain: str, key: str) -> UUID:
    return uuid5(namespace, f"{domain}{key}")


__all__ = [
    "DefaultTenantControlRegistrationResult",
    "DefaultTenantDatabaseIdentityResult",
    "DefaultTenantInPlaceRegistrationService",
    "DefaultTenantRegistrationConflictError",
    "DefaultTenantRegistrationError",
    "DefaultTenantRegistrationInputError",
    "DefaultTenantRegistrationPersistenceError",
    "DefaultTenantRegistrationTransactionError",
    "DefaultTenantRouteRegistration",
]
