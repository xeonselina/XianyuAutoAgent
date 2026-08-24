"""Tenant-side current Kuaimai printer binding without provider I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin
from sqlalchemy.orm.scoping import scoped_session

from app.models.warehouse import Warehouse, WarehousePrinter


class WarehousePrinterBindingError(RuntimeError):
    code = "WAREHOUSE_PRINTER_BINDING_FAILED"


class WarehousePrinterBindingInputError(WarehousePrinterBindingError):
    code = "WAREHOUSE_PRINTER_BINDING_INPUT_INVALID"


class WarehousePrinterBindingConflictError(WarehousePrinterBindingError):
    code = "WAREHOUSE_PRINTER_BINDING_CONFLICT"


class WarehousePrinterBindingUnavailableError(WarehousePrinterBindingError):
    code = "WAREHOUSE_PRINTER_BINDING_UNAVAILABLE"


class WarehousePrinterBindingTransactionError(WarehousePrinterBindingError):
    code = "WAREHOUSE_PRINTER_BINDING_TRANSACTION_INVALID"


@dataclass(frozen=True, slots=True)
class WarehousePrinterBindingRef:
    warehouse_id: int
    warehouse_uuid: str
    printer_sn: str
    display_name: str
    provider: str
    status: str
    last_verified_at: datetime
    idempotent_replay: bool = False


class WarehousePrinterBindingService:
    """Persist or resolve one provider-verified current printer binding."""

    def __init__(self, tenant_session: Session) -> None:
        if isinstance(tenant_session, scoped_session):
            tenant_session = tenant_session()
        if not isinstance(tenant_session, Session):
            raise WarehousePrinterBindingTransactionError()
        self._session = tenant_session

    def bind_verified_kuaimai_printer(
        self,
        *,
        warehouse_id: int,
        printer_sn: str,
        display_name: str,
        verified_at: datetime,
    ) -> WarehousePrinterBindingRef:
        """Apply metadata already verified against one exact Kuaimai revision."""

        self._require_transaction()
        selected_warehouse_id = _positive(warehouse_id)
        selected_sn = _text(printer_sn, maximum=128)
        selected_name = _text(display_name, maximum=120)
        selected_time = _datetime(verified_at)
        warehouse = self._lock_ready_warehouse(selected_warehouse_id)
        binding = self._lock_binding(warehouse.id)
        sn_owner = self._lock_sn_owner(selected_sn)
        if sn_owner is not None and sn_owner.warehouse_id != warehouse.id:
            raise WarehousePrinterBindingConflictError()
        if (
            binding is not None
            and binding.printer_sn == selected_sn
            and binding.display_name == selected_name
            and binding.provider == "kuaimai"
            and binding.status == "active"
            and binding.last_verified_at is not None
            and _datetime(binding.last_verified_at) == selected_time
        ):
            return _binding_ref(binding, warehouse, replay=True)
        if binding is None:
            binding = WarehousePrinter(
                warehouse_id=warehouse.id,
                printer_sn=selected_sn,
                display_name=selected_name,
                provider="kuaimai",
                status="active",
                last_verified_at=selected_time,
                created_at=selected_time,
                updated_at=selected_time,
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
                    or winner.printer_sn != selected_sn
                    or winner.display_name != selected_name
                    or winner.provider != "kuaimai"
                    or winner.status != "active"
                    or winner.last_verified_at is None
                    or _datetime(winner.last_verified_at) != selected_time
                ):
                    raise WarehousePrinterBindingConflictError() from None
                return _binding_ref(winner, warehouse, replay=True)
            return _binding_ref(binding, warehouse)

        binding.printer_sn = selected_sn
        binding.display_name = selected_name
        binding.provider = "kuaimai"
        binding.status = "active"
        binding.last_verified_at = selected_time
        binding.updated_at = selected_time
        try:
            self._session.flush()
        except IntegrityError:
            raise WarehousePrinterBindingConflictError() from None
        return _binding_ref(binding, warehouse)

    def resolve_active_kuaimai_printer(
        self,
        *,
        warehouse_id: int,
        expected_printer_sn: str | None = None,
    ) -> WarehousePrinterBindingRef:
        self._require_transaction()
        warehouse = self._lock_ready_warehouse(_positive(warehouse_id))
        binding = self._lock_binding(warehouse.id)
        expected_sn = (
            None
            if expected_printer_sn is None
            else _text(expected_printer_sn, maximum=128)
        )
        if (
            binding is None
            or binding.provider != "kuaimai"
            or binding.status != "active"
            or binding.last_verified_at is None
            or (
                expected_sn is not None
                and binding.printer_sn != expected_sn
            )
        ):
            raise WarehousePrinterBindingUnavailableError()
        return _binding_ref(binding, warehouse)

    def _lock_ready_warehouse(self, warehouse_id: int) -> Warehouse:
        warehouse = self._session.scalar(
            sa.select(Warehouse)
            .where(Warehouse.id == warehouse_id)
            .with_for_update()
        )
        if (
            warehouse is None
            or warehouse.status != "active"
            or warehouse.setup_state != "ready"
        ):
            raise WarehousePrinterBindingUnavailableError()
        return warehouse

    def _lock_binding(self, warehouse_id: int) -> WarehousePrinter | None:
        return self._session.scalar(
            sa.select(WarehousePrinter)
            .where(WarehousePrinter.warehouse_id == warehouse_id)
            .with_for_update()
        )

    def _lock_sn_owner(self, printer_sn: str) -> WarehousePrinter | None:
        return self._session.scalar(
            sa.select(WarehousePrinter)
            .where(WarehousePrinter.printer_sn == printer_sn)
            .with_for_update()
        )

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise WarehousePrinterBindingTransactionError()


def _binding_ref(
    binding: WarehousePrinter,
    warehouse: Warehouse,
    *,
    replay: bool = False,
) -> WarehousePrinterBindingRef:
    if binding.last_verified_at is None:
        raise WarehousePrinterBindingUnavailableError()
    return WarehousePrinterBindingRef(
        warehouse_id=warehouse.id,
        warehouse_uuid=warehouse.warehouse_uuid,
        printer_sn=binding.printer_sn,
        display_name=binding.display_name,
        provider=binding.provider,
        status=binding.status,
        last_verified_at=_datetime(binding.last_verified_at),
        idempotent_replay=replay,
    )


def _positive(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WarehousePrinterBindingInputError()
    return value


def _text(value: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise WarehousePrinterBindingInputError()
    return value


def _datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise WarehousePrinterBindingInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "WarehousePrinterBindingConflictError",
    "WarehousePrinterBindingError",
    "WarehousePrinterBindingInputError",
    "WarehousePrinterBindingRef",
    "WarehousePrinterBindingService",
    "WarehousePrinterBindingTransactionError",
    "WarehousePrinterBindingUnavailableError",
]
