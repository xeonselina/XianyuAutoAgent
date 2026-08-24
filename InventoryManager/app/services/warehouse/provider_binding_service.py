"""Tenant-database SF warehouse binding transitions without provider I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin
from sqlalchemy.orm.scoping import scoped_session

from app.models.warehouse import Warehouse, WarehouseProviderBinding


class WarehouseProviderBindingError(RuntimeError):
    code = "WAREHOUSE_PROVIDER_BINDING_FAILED"
    public_message = "warehouse provider binding operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class WarehouseProviderBindingInputError(WarehouseProviderBindingError):
    code = "WAREHOUSE_PROVIDER_BINDING_INPUT_INVALID"


class WarehouseProviderBindingConflictError(WarehouseProviderBindingError):
    code = "WAREHOUSE_PROVIDER_BINDING_CONFLICT"


class WarehouseProviderBindingUnavailableError(WarehouseProviderBindingError):
    code = "WAREHOUSE_PROVIDER_BINDING_UNAVAILABLE"


class WarehouseProviderBindingTransactionError(WarehouseProviderBindingError):
    code = "WAREHOUSE_PROVIDER_BINDING_TRANSACTION_INVALID"


@dataclass(frozen=True, slots=True)
class WarehouseProviderBindingRef:
    warehouse_id: int
    warehouse_uuid: str
    provider: str
    provider_account_uuid: str | None
    binding_revision: int
    status: str
    verified_at: datetime | None
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class WarehouseProviderBindingPlan:
    """Immutable local CAS facts bound into one control-plane D48 action."""

    warehouse_id: int
    warehouse_uuid: str
    provider_account_uuid: str
    expected_provider_account_uuid: str | None
    expected_binding_revision: int | None
    target_binding_revision: int
    binding_already_current: bool


@dataclass(frozen=True, slots=True)
class WarehouseProviderUnbindingPlan:
    warehouse_id: int
    warehouse_uuid: str
    provider_account_uuid: str
    expected_binding_revision: int
    binding_already_removed: bool


class WarehouseProviderBindingService:
    """Apply one already-authorized control-plane binding fact locally."""

    def __init__(self, tenant_session: Session) -> None:
        if isinstance(tenant_session, scoped_session):
            tenant_session = tenant_session()
        if not isinstance(tenant_session, Session):
            raise WarehouseProviderBindingTransactionError()
        self._session = tenant_session

    def bind_sf_account(
        self,
        *,
        warehouse_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        binding_revision: int,
        actor_user_uuid: str | UUID,
        verified_at: datetime,
        expected_provider_account_uuid: str | UUID | None,
        expected_binding_revision: int | None,
    ) -> WarehouseProviderBindingRef:
        self._require_transaction()
        warehouse_id = _uuid(warehouse_uuid)
        account_id = _uuid(provider_account_uuid)
        actor_id = _uuid(actor_user_uuid)
        selected_revision = _positive(binding_revision)
        expected_account = _optional_uuid(expected_provider_account_uuid)
        expected_revision = _optional_positive(expected_binding_revision)
        selected_verified_at = _datetime(verified_at)
        warehouse = self._lock_ready_warehouse(warehouse_id)
        binding = self._lock_binding(warehouse.id)
        if binding is not None and (
            binding.status == "active"
            and binding.provider_account_uuid == account_id
            and binding.binding_revision == selected_revision
        ):
            return _binding_ref(binding, warehouse, replay=True)
        if binding is None:
            if (
                expected_account is not None
                or expected_revision is not None
                or selected_revision != 1
            ):
                raise WarehouseProviderBindingConflictError()
            binding = WarehouseProviderBinding(
                warehouse_id=warehouse.id,
                provider="sf",
                provider_account_uuid=account_id,
                binding_revision=selected_revision,
                status="active",
                verified_at=selected_verified_at,
                bound_by=actor_id,
                created_at=selected_verified_at,
                updated_at=selected_verified_at,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(binding)
                    self._session.flush()
            except IntegrityError:
                self._session.expire_all()
                winner = self._lock_binding(warehouse.id)
                if (
                    winner is None
                    or winner.status != "active"
                    or winner.provider_account_uuid != account_id
                    or winner.binding_revision != selected_revision
                ):
                    raise WarehouseProviderBindingConflictError() from None
                return _binding_ref(winner, warehouse, replay=True)
            return _binding_ref(binding, warehouse)

        if (
            binding.provider_account_uuid != expected_account
            or binding.binding_revision != expected_revision
            or selected_revision != binding.binding_revision + 1
        ):
            raise WarehouseProviderBindingConflictError()
        changed = self._session.execute(
            sa.update(WarehouseProviderBinding)
            .where(
                WarehouseProviderBinding.warehouse_id == warehouse.id,
                WarehouseProviderBinding.provider == "sf",
                WarehouseProviderBinding.binding_revision == expected_revision,
                _nullable_equal(
                    WarehouseProviderBinding.provider_account_uuid,
                    expected_account,
                ),
            )
            .values(
                provider_account_uuid=account_id,
                binding_revision=selected_revision,
                status="active",
                verified_at=selected_verified_at,
                bound_by=actor_id,
                updated_at=selected_verified_at,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise WarehouseProviderBindingConflictError()
        return _binding_ref(self._refresh_binding(warehouse.id), warehouse)

    def resolve_active_sf_binding(
        self,
        *,
        warehouse_uuid: str | UUID,
    ) -> WarehouseProviderBindingRef:
        """Return the trusted local half of a control-plane context lookup."""

        self._require_transaction()
        warehouse = self._lock_ready_warehouse(_uuid(warehouse_uuid))
        binding = self._lock_binding(warehouse.id)
        if (
            binding is None
            or binding.status != "active"
            or binding.provider_account_uuid is None
            or binding.binding_revision < 1
            or binding.verified_at is None
        ):
            raise WarehouseProviderBindingUnavailableError()
        return _binding_ref(binding, warehouse)

    def plan_sf_account_binding(
        self,
        *,
        warehouse_uuid: str | UUID,
        provider_account_uuid: str | UUID,
    ) -> WarehouseProviderBindingPlan:
        """Lock and snapshot the local half before an external validation saga."""

        self._require_transaction()
        account_id = _uuid(provider_account_uuid)
        warehouse = self._lock_ready_warehouse(_uuid(warehouse_uuid))
        binding = self._lock_binding(warehouse.id)
        if binding is None:
            return WarehouseProviderBindingPlan(
                warehouse_id=warehouse.id,
                warehouse_uuid=warehouse.warehouse_uuid,
                provider_account_uuid=account_id,
                expected_provider_account_uuid=None,
                expected_binding_revision=None,
                target_binding_revision=1,
                binding_already_current=False,
            )
        already_current = bool(
            binding.status == "active"
            and binding.provider_account_uuid == account_id
        )
        return WarehouseProviderBindingPlan(
            warehouse_id=warehouse.id,
            warehouse_uuid=warehouse.warehouse_uuid,
            provider_account_uuid=account_id,
            expected_provider_account_uuid=binding.provider_account_uuid,
            expected_binding_revision=binding.binding_revision,
            target_binding_revision=(
                binding.binding_revision
                if already_current
                else binding.binding_revision + 1
            ),
            binding_already_current=already_current,
        )

    def plan_sf_account_unbinding(
        self,
        *,
        warehouse_uuid: str | UUID,
        provider_account_uuid: str | UUID,
    ) -> WarehouseProviderUnbindingPlan:
        """Snapshot active removal CAS or recognize its exact local terminal shape."""

        self._require_transaction()
        account_id = _uuid(provider_account_uuid)
        warehouse = self._lock_warehouse(_uuid(warehouse_uuid))
        binding = self._lock_binding(warehouse.id)
        if binding is None:
            raise WarehouseProviderBindingUnavailableError()
        if (
            binding.status == "active"
            and binding.provider_account_uuid == account_id
        ):
            return WarehouseProviderUnbindingPlan(
                warehouse_id=warehouse.id,
                warehouse_uuid=warehouse.warehouse_uuid,
                provider_account_uuid=account_id,
                expected_binding_revision=binding.binding_revision,
                binding_already_removed=False,
            )
        if (
            binding.status == "inactive"
            and binding.provider_account_uuid is None
            and binding.binding_revision >= 2
        ):
            return WarehouseProviderUnbindingPlan(
                warehouse_id=warehouse.id,
                warehouse_uuid=warehouse.warehouse_uuid,
                provider_account_uuid=account_id,
                expected_binding_revision=binding.binding_revision - 1,
                binding_already_removed=True,
            )
        raise WarehouseProviderBindingConflictError()

    def unbind_sf_account(
        self,
        *,
        warehouse_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        expected_binding_revision: int,
        actor_user_uuid: str | UUID,
        occurred_at: datetime,
    ) -> WarehouseProviderBindingRef:
        self._require_transaction()
        warehouse_id = _uuid(warehouse_uuid)
        account_id = _uuid(provider_account_uuid)
        actor_id = _uuid(actor_user_uuid)
        expected_revision = _positive(expected_binding_revision)
        selected_time = _datetime(occurred_at)
        warehouse = self._lock_warehouse(warehouse_id)
        binding = self._lock_binding(warehouse.id)
        if (
            binding is not None
            and binding.status == "inactive"
            and binding.provider_account_uuid is None
            and binding.binding_revision == expected_revision + 1
        ):
            return _binding_ref(binding, warehouse, replay=True)
        if (
            binding is None
            or binding.status != "active"
            or binding.provider_account_uuid != account_id
            or binding.binding_revision != expected_revision
        ):
            raise WarehouseProviderBindingConflictError()
        changed = self._session.execute(
            sa.update(WarehouseProviderBinding)
            .where(
                WarehouseProviderBinding.warehouse_id == warehouse.id,
                WarehouseProviderBinding.provider == "sf",
                WarehouseProviderBinding.status == "active",
                WarehouseProviderBinding.provider_account_uuid == account_id,
                WarehouseProviderBinding.binding_revision == expected_revision,
            )
            .values(
                provider_account_uuid=None,
                binding_revision=expected_revision + 1,
                status="inactive",
                verified_at=None,
                bound_by=actor_id,
                updated_at=selected_time,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise WarehouseProviderBindingConflictError()
        return _binding_ref(self._refresh_binding(warehouse.id), warehouse)

    def _lock_ready_warehouse(self, warehouse_uuid: str) -> Warehouse:
        warehouse = self._lock_warehouse(warehouse_uuid)
        if warehouse.status != "active" or warehouse.setup_state != "ready":
            raise WarehouseProviderBindingUnavailableError()
        return warehouse

    def _lock_warehouse(self, warehouse_uuid: str) -> Warehouse:
        warehouse = self._session.scalar(
            sa.select(Warehouse)
            .where(Warehouse.warehouse_uuid == warehouse_uuid)
            .with_for_update()
        )
        if warehouse is None:
            raise WarehouseProviderBindingUnavailableError()
        return warehouse

    def _lock_binding(self, warehouse_id: int) -> WarehouseProviderBinding | None:
        return self._session.scalar(
            sa.select(WarehouseProviderBinding)
            .where(
                WarehouseProviderBinding.warehouse_id == warehouse_id,
                WarehouseProviderBinding.provider == "sf",
            )
            .with_for_update()
        )

    def _refresh_binding(self, warehouse_id: int) -> WarehouseProviderBinding:
        return self._session.execute(
            sa.select(WarehouseProviderBinding)
            .where(
                WarehouseProviderBinding.warehouse_id == warehouse_id,
                WarehouseProviderBinding.provider == "sf",
            )
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise WarehouseProviderBindingTransactionError()


def _binding_ref(
    binding: WarehouseProviderBinding,
    warehouse: Warehouse,
    *,
    replay: bool = False,
) -> WarehouseProviderBindingRef:
    return WarehouseProviderBindingRef(
        warehouse_id=warehouse.id,
        warehouse_uuid=warehouse.warehouse_uuid,
        provider=binding.provider,
        provider_account_uuid=binding.provider_account_uuid,
        binding_revision=binding.binding_revision,
        status=binding.status,
        verified_at=(
            None if binding.verified_at is None else _datetime(binding.verified_at)
        ),
        idempotent_replay=replay,
    )


def _uuid(value: str | UUID) -> str:
    try:
        selected = value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise WarehouseProviderBindingInputError() from None
    return str(selected)


def _optional_uuid(value: str | UUID | None) -> str | None:
    return None if value is None else _uuid(value)


def _positive(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WarehouseProviderBindingInputError()
    return value


def _optional_positive(value: int | None) -> int | None:
    return None if value is None else _positive(value)


def _datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise WarehouseProviderBindingInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _nullable_equal(column: object, value: str | None):
    return column.is_(None) if value is None else column == value
