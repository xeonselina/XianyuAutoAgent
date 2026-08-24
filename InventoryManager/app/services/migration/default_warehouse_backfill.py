"""Idempotent first-stage default-tenant warehouse/device backfill.

The service accepts an already routed tenant SQLAlchemy ``Session``.  It never
selects a database, touches the control plane or a provider, and never commits
or rolls back the caller's outer transaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.warehouse import Warehouse
from inventory_control.transactions import require_caller_transaction


_BASELINE_ID: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}",
    re.ASCII,
)
_WAREHOUSE_UUID_DOMAIN: Final = "inventory-manager/default-warehouse/v1/"
_READY_FIELD_LIMITS: Final = {
    "name": 120,
    "contact_name": 120,
    "contact_phone": 32,
    "province": 64,
    "city": 64,
    "district": 64,
    "address_detail": 255,
}


class DefaultWarehouseBackfillError(RuntimeError):
    """Stable error that never includes warehouse profile values."""

    code = "DEFAULT_WAREHOUSE_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultWarehouseBackfillInputError(DefaultWarehouseBackfillError):
    code = "DEFAULT_WAREHOUSE_BACKFILL_INPUT_INVALID"


class DefaultWarehouseBackfillTransactionError(DefaultWarehouseBackfillError):
    code = "DEFAULT_WAREHOUSE_BACKFILL_TRANSACTION_INVALID"


class DefaultWarehouseIdentityMismatchError(DefaultWarehouseBackfillError):
    code = "DEFAULT_WAREHOUSE_IDENTITY_MISMATCH"


class DefaultWarehouseConflictError(DefaultWarehouseBackfillError):
    code = "DEFAULT_WAREHOUSE_CONFLICT"


class DefaultWarehousePersistenceError(DefaultWarehouseBackfillError):
    code = "DEFAULT_WAREHOUSE_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True, repr=False)
class DefaultWarehouseProfile:
    """All-missing pending input or a complete normalized ready profile."""

    name: str | None = field(default=None, repr=False)
    contact_name: str | None = field(default=None, repr=False)
    contact_phone: str | None = field(default=None, repr=False)
    province: str | None = field(default=None, repr=False)
    city: str | None = field(default=None, repr=False)
    district: str | None = field(default=None, repr=False)
    address_detail: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        values = {name: getattr(self, name) for name in _READY_FIELD_LIMITS}
        if all(value is None for value in values.values()):
            return
        if any(value is None for value in values.values()):
            raise DefaultWarehouseBackfillInputError()
        for name, limit in _READY_FIELD_LIMITS.items():
            value = values[name]
            if not isinstance(value, str):
                raise DefaultWarehouseBackfillInputError()
            normalized = value.strip()
            if not normalized or len(normalized) > limit:
                raise DefaultWarehouseBackfillInputError()
            object.__setattr__(self, name, normalized)

    @property
    def setup_state(self) -> str:
        return "pending" if self.name is None else "ready"

    def __repr__(self) -> str:
        return (
            "DefaultWarehouseProfile("
            f"setup_state={self.setup_state!r}, fields='<redacted>')"
        )


@dataclass(frozen=True, slots=True)
class DefaultWarehouseBackfillResult:
    warehouse_id: int
    warehouse_uuid: UUID
    setup_state: str
    warehouse_created: bool
    assigned_device_ids: tuple[int, ...]
    preserved_assigned_device_count: int
    idempotent_replay: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.warehouse_id, int)
            or isinstance(self.warehouse_id, bool)
            or self.warehouse_id <= 0
            or not isinstance(self.warehouse_uuid, UUID)
            or self.warehouse_uuid.int == 0
            or self.setup_state not in {"pending", "ready"}
            or not isinstance(self.warehouse_created, bool)
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item <= 0
                for item in self.assigned_device_ids
            )
            or tuple(sorted(set(self.assigned_device_ids))) != self.assigned_device_ids
            or not isinstance(self.preserved_assigned_device_count, int)
            or isinstance(self.preserved_assigned_device_count, bool)
            or self.preserved_assigned_device_count < 0
            or not isinstance(self.idempotent_replay, bool)
        ):
            raise DefaultWarehousePersistenceError()


def derive_default_warehouse_uuid(
    *,
    database_uuid: UUID,
    baseline_migration_id: str,
) -> UUID:
    """Derive the stable default warehouse identity from immutable inputs."""

    selected_database = _required_uuid(database_uuid)
    selected_baseline = _baseline_id(baseline_migration_id)
    return uuid5(
        selected_database,
        f"{_WAREHOUSE_UUID_DOMAIN}{selected_baseline}",
    )


class DefaultWarehouseBackfillService:
    """Create/replay the default warehouse, then assign unowned devices."""

    def backfill(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        database_uuid: UUID,
        expected_schema_generation: int,
        baseline_migration_id: str,
        profile: DefaultWarehouseProfile,
    ) -> DefaultWarehouseBackfillResult:
        selected_tenant = _required_uuid(tenant_uuid)
        selected_database = _required_uuid(database_uuid)
        if selected_tenant == selected_database:
            raise DefaultWarehouseBackfillInputError()
        generation = _positive_generation(expected_schema_generation)
        expected_warehouse_uuid = derive_default_warehouse_uuid(
            database_uuid=selected_database,
            baseline_migration_id=baseline_migration_id,
        )
        if not isinstance(profile, DefaultWarehouseProfile):
            raise DefaultWarehouseBackfillInputError()

        require_caller_transaction(
            session,
            DefaultWarehouseBackfillTransactionError,
            invalid_session_error=DefaultWarehouseBackfillInputError,
            clean=True,
        )
        identities = _lock_identity(session)
        identity = _verified_identity(
            identities,
            tenant_uuid=selected_tenant,
            database_uuid=selected_database,
            schema_generation=generation,
        )
        del identity
        warehouses = _lock_warehouses(session)
        warehouse, created = _select_default_warehouse(
            warehouses,
            expected_uuid=expected_warehouse_uuid,
            profile=profile,
        )

        try:
            with session.begin_nested():
                if created:
                    session.add(warehouse)
                    session.flush()
                devices = _lock_devices(session)
                _verify_existing_device_assignments(
                    devices,
                    warehouse_ids={item.id for item in warehouses} | {warehouse.id},
                )
                assigned = []
                preserved = 0
                for device in devices:
                    if device.warehouse_id is None:
                        device.warehouse_id = warehouse.id
                        assigned.append(device.id)
                    else:
                        preserved += 1
                session.flush()
        except DefaultWarehouseBackfillError:
            raise
        except IntegrityError:
            raise DefaultWarehouseConflictError() from None
        except SQLAlchemyError:
            raise DefaultWarehousePersistenceError() from None

        assigned_ids = tuple(sorted(assigned))
        return DefaultWarehouseBackfillResult(
            warehouse_id=warehouse.id,
            warehouse_uuid=expected_warehouse_uuid,
            setup_state=profile.setup_state,
            warehouse_created=created,
            assigned_device_ids=assigned_ids,
            preserved_assigned_device_count=preserved,
            idempotent_replay=not created and not assigned_ids,
        )


def _lock_identity(session: Session) -> tuple[TenantDatabaseIdentity, ...]:
    try:
        return tuple(
            session.scalars(
                sa.select(TenantDatabaseIdentity)
                .order_by(TenantDatabaseIdentity.singleton_key)
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise DefaultWarehousePersistenceError() from None


def _verified_identity(
    identities: tuple[TenantDatabaseIdentity, ...],
    *,
    tenant_uuid: UUID,
    database_uuid: UUID,
    schema_generation: int,
) -> TenantDatabaseIdentity:
    if len(identities) != 1:
        raise DefaultWarehouseIdentityMismatchError()
    identity = identities[0]
    try:
        stored_tenant = UUID(identity.tenant_id)
        stored_database = UUID(identity.database_uuid)
    except (AttributeError, TypeError, ValueError):
        raise DefaultWarehouseIdentityMismatchError() from None
    if (
        identity.singleton_key != 1
        or stored_tenant.int == 0
        or stored_database.int == 0
        or str(stored_tenant) != identity.tenant_id
        or str(stored_database) != identity.database_uuid
        or stored_tenant != tenant_uuid
        or stored_database != database_uuid
        or identity.schema_generation != schema_generation
    ):
        raise DefaultWarehouseIdentityMismatchError()
    return identity


def _lock_warehouses(session: Session) -> tuple[Warehouse, ...]:
    try:
        return tuple(
            session.scalars(
                sa.select(Warehouse)
                .order_by(Warehouse.id)
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise DefaultWarehousePersistenceError() from None


def _select_default_warehouse(
    warehouses: tuple[Warehouse, ...],
    *,
    expected_uuid: UUID,
    profile: DefaultWarehouseProfile,
) -> tuple[Warehouse, bool]:
    defaults = tuple(
        item
        for item in warehouses
        if item.is_default is True or item.default_slot is not None
    )
    matching_uuid = tuple(
        item for item in warehouses if item.warehouse_uuid == str(expected_uuid)
    )
    if len(defaults) > 1 or len(matching_uuid) > 1:
        raise DefaultWarehouseConflictError()
    if not defaults:
        if matching_uuid:
            raise DefaultWarehouseConflictError()
        values = _profile_values(profile)
        return (
            Warehouse(
                warehouse_uuid=str(expected_uuid),
                status="active",
                setup_state=profile.setup_state,
                is_default=True,
                default_slot=1,
                **values,
            ),
            True,
        )

    warehouse = defaults[0]
    if len(matching_uuid) != 1 or matching_uuid[0] is not warehouse:
        raise DefaultWarehouseConflictError()
    expected_values = _profile_values(profile)
    if (
        warehouse.warehouse_uuid != str(expected_uuid)
        or warehouse.status != "active"
        or warehouse.setup_state != profile.setup_state
        or warehouse.is_default is not True
        or warehouse.default_slot != 1
        or any(
            getattr(warehouse, name) != value for name, value in expected_values.items()
        )
    ):
        raise DefaultWarehouseConflictError()
    return warehouse, False


def _profile_values(profile: DefaultWarehouseProfile) -> dict[str, str | None]:
    return {name: getattr(profile, name) for name in _READY_FIELD_LIMITS}


def _lock_devices(session: Session) -> tuple[Device, ...]:
    try:
        return tuple(
            session.scalars(
                sa.select(Device)
                .order_by(Device.id)
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise DefaultWarehousePersistenceError() from None


def _verify_existing_device_assignments(
    devices: tuple[Device, ...],
    *,
    warehouse_ids: set[int],
) -> None:
    if any(
        device.id is None
        or (
            device.warehouse_id is not None and device.warehouse_id not in warehouse_ids
        )
        for device in devices
    ):
        raise DefaultWarehouseConflictError()


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise DefaultWarehouseBackfillInputError()
    return value


def _positive_generation(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DefaultWarehouseBackfillInputError()
    return value


def _baseline_id(value: object) -> str:
    if not isinstance(value, str) or _BASELINE_ID.fullmatch(value) is None:
        raise DefaultWarehouseBackfillInputError()
    return value


__all__ = [
    "DefaultWarehouseBackfillError",
    "DefaultWarehouseBackfillInputError",
    "DefaultWarehouseBackfillResult",
    "DefaultWarehouseBackfillService",
    "DefaultWarehouseBackfillTransactionError",
    "DefaultWarehouseConflictError",
    "DefaultWarehouseIdentityMismatchError",
    "DefaultWarehousePersistenceError",
    "DefaultWarehouseProfile",
    "derive_default_warehouse_uuid",
]
