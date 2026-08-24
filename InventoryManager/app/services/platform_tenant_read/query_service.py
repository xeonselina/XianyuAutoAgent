"""Pure SELECT projections for one platform-selected tenant schema."""

from __future__ import annotations

from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse


_RENTAL_STATUSES = frozenset(
    {
        "not_shipped",
        "scheduled_for_shipping",
        "shipped",
        "returned",
        "completed",
        "cancelled",
    }
)
_DEVICE_STATUSES = frozenset(
    {"active", "sold", "decommissioned", "damaged", "retired"}
)
_WAREHOUSE_STATUSES = frozenset({"active", "inactive"})
_WAREHOUSE_SETUP_STATES = frozenset({"pending", "ready"})


class PlatformTenantQueryInputError(ValueError):
    pass


class PlatformTenantBusinessQueryService:
    """Return bounded DTOs without ORM traversal or unmasked customer PII."""

    def __init__(self, *, maximum_execution_time_ms: int) -> None:
        if (
            isinstance(maximum_execution_time_ms, bool)
            or not isinstance(maximum_execution_time_ms, int)
            or not 100 <= maximum_execution_time_ms <= 10_000
        ):
            raise ValueError("platform read query timeout is invalid")
        self._maximum_execution_time_ms = maximum_execution_time_ms

    def list_rentals(
        self,
        session: Session,
        *,
        page: object,
        page_size: object,
        status: object = None,
    ) -> dict[str, object]:
        _require_active_session(session)
        selected_page = _bounded_integer(page, minimum=1, maximum=100_000)
        selected_size = _bounded_integer(page_size, minimum=1, maximum=100)
        selected_status = _status(status)
        statement = (
            sa.select(
                Rental.id,
                Rental.device_id,
                Device.name.label("device_name"),
                Device.model.label("device_model"),
                Rental.start_date,
                Rental.end_date,
                Rental.status,
                Rental.customer_name,
                Rental.customer_phone,
                Rental.customer_province,
                Rental.customer_city,
                Rental.customer_district,
                Rental.order_amount,
                Rental.actual_shipped_at,
                Rental.actual_returned_at,
                Rental.created_at,
                Rental.updated_at,
            )
            .select_from(Rental)
            .join(Device, Device.id == Rental.device_id)
            .where(Rental.parent_rental_id.is_(None))
        )
        if selected_status is not None:
            statement = statement.where(Rental.status == selected_status)
        rows = session.execute(
            self._bounded(statement).order_by(Rental.id.desc())
            .offset((selected_page - 1) * selected_size)
            .limit(selected_size + 1)
        ).all()
        visible = rows[:selected_size]
        return {
            "items": [
                {
                    "rental_id": row.id,
                    "device": {
                        "device_id": row.device_id,
                        "name": row.device_name,
                        "model": row.device_model,
                    },
                    "start_date": _date(row.start_date),
                    "end_date": _date(row.end_date),
                    "status": row.status,
                    "customer": {
                        "name_masked": _mask_name(row.customer_name),
                        "phone_masked": _mask_phone(row.customer_phone),
                        "region_masked": _mask_region(
                            row.customer_province,
                            row.customer_city,
                            row.customer_district,
                        ),
                    },
                    "order_amount": (
                        None
                        if row.order_amount is None
                        else str(row.order_amount)
                    ),
                    "actual_shipped_at": _iso(row.actual_shipped_at),
                    "actual_returned_at": _iso(row.actual_returned_at),
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in visible
            ],
            "page": selected_page,
            "page_size": selected_size,
            "has_more": len(rows) > selected_size,
            "status_filter": selected_status,
        }

    def list_devices(
        self,
        session: Session,
        *,
        page: object,
        page_size: object,
        lifecycle_status: object = None,
    ) -> dict[str, object]:
        """Return one bounded device projection without free-text reasons."""

        _require_active_session(session)
        selected_page = _bounded_integer(page, minimum=1, maximum=100_000)
        selected_size = _bounded_integer(page_size, minimum=1, maximum=100)
        selected_status = _optional_enum(
            lifecycle_status,
            allowed=_DEVICE_STATUSES,
        )
        statement = sa.select(
            Device.id,
            Device.name,
            Device.model,
            Device.model_id,
            Device.is_accessory,
            Device.warehouse_id,
            Device.lifecycle_status,
            Device.lifecycle_date,
            Device.created_at,
            Device.updated_at,
        )
        if selected_status is not None:
            statement = statement.where(
                Device.lifecycle_status == selected_status
            )
        rows = session.execute(
            self._bounded(statement)
            .order_by(Device.id.desc())
            .offset((selected_page - 1) * selected_size)
            .limit(selected_size + 1)
        ).all()
        return {
            "items": [
                {
                    "device_id": row.id,
                    "name": row.name,
                    "model": row.model,
                    "model_id": row.model_id,
                    "is_accessory": row.is_accessory,
                    "warehouse_id": row.warehouse_id,
                    "lifecycle_status": row.lifecycle_status,
                    "lifecycle_date": _iso(row.lifecycle_date),
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows[:selected_size]
            ],
            "page": selected_page,
            "page_size": selected_size,
            "has_more": len(rows) > selected_size,
            "lifecycle_status_filter": selected_status,
        }

    def list_warehouses(
        self,
        session: Session,
        *,
        page: object,
        page_size: object,
        status: object = None,
        setup_state: object = None,
    ) -> dict[str, object]:
        """Return warehouse state without contact, address, or printer data."""

        _require_active_session(session)
        selected_page = _bounded_integer(page, minimum=1, maximum=100_000)
        selected_size = _bounded_integer(page_size, minimum=1, maximum=100)
        selected_status = _optional_enum(
            status,
            allowed=_WAREHOUSE_STATUSES,
        )
        selected_setup = _optional_enum(
            setup_state,
            allowed=_WAREHOUSE_SETUP_STATES,
        )
        statement = sa.select(
            Warehouse.id,
            Warehouse.warehouse_uuid,
            Warehouse.name,
            Warehouse.status,
            Warehouse.setup_state,
            Warehouse.is_default,
            Warehouse.created_at,
            Warehouse.updated_at,
        )
        if selected_status is not None:
            statement = statement.where(Warehouse.status == selected_status)
        if selected_setup is not None:
            statement = statement.where(
                Warehouse.setup_state == selected_setup
            )
        rows = session.execute(
            self._bounded(statement)
            .order_by(Warehouse.id.desc())
            .offset((selected_page - 1) * selected_size)
            .limit(selected_size + 1)
        ).all()
        return {
            "items": [
                {
                    "warehouse_id": row.id,
                    "warehouse_uuid": row.warehouse_uuid,
                    "name": row.name,
                    "status": row.status,
                    "setup_state": row.setup_state,
                    "is_default": row.is_default,
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows[:selected_size]
            ],
            "page": selected_page,
            "page_size": selected_size,
            "has_more": len(rows) > selected_size,
            "status_filter": selected_status,
            "setup_state_filter": selected_setup,
        }

    def get_customer_pii(
        self,
        session: Session,
        *,
        rental_id: object,
    ) -> dict[str, object] | None:
        """Return one exact main-rental customer projection, never a search."""

        _require_active_session(session)
        selected_id = _bounded_integer(
            rental_id,
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        statement = (
            sa.select(
                Rental.id,
                Rental.customer_name,
                Rental.customer_phone,
                Rental.customer_province,
                Rental.customer_city,
                Rental.customer_district,
                Rental.customer_address_detail,
            )
            .where(
                Rental.id == selected_id,
                Rental.parent_rental_id.is_(None),
            )
        )
        row = session.execute(self._bounded(statement)).one_or_none()
        if row is None:
            return None
        return {
            "rental_id": row.id,
            "customer": {
                "name": row.customer_name,
                "phone": row.customer_phone,
                "address": {
                    "province": row.customer_province,
                    "city": row.customer_city,
                    "district": row.customer_district,
                    "detail": row.customer_address_detail,
                },
            },
        }

    def _bounded(self, statement):
        return statement.prefix_with(
            f"/*+ MAX_EXECUTION_TIME({self._maximum_execution_time_ms}) */",
            dialect="mysql",
        )


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int:
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        raise PlatformTenantQueryInputError() from None
    if (
        isinstance(value, bool)
        or not minimum <= selected <= maximum
        or (isinstance(value, str) and str(selected) != value)
    ):
        raise PlatformTenantQueryInputError()
    return selected


def _status(value: object) -> str | None:
    return _optional_enum(value, allowed=_RENTAL_STATUSES)


def _optional_enum(value: object, *, allowed: frozenset[str]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in allowed:
        raise PlatformTenantQueryInputError()
    return value


def _require_active_session(session: Session) -> None:
    if not isinstance(session, Session) or not session.in_transaction():
        raise TypeError("platform tenant read requires an active Session")


# Compatibility aliases for the original rental-only slice.
PlatformTenantRentalQueryInputError = PlatformTenantQueryInputError
PlatformTenantRentalQueryService = PlatformTenantBusinessQueryService


def _mask_name(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[0] + "**"


def _mask_phone(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    digits = "".join(
        character
        for character in value
        if character.isascii() and character.isdigit()
    )
    if len(digits) < 4:
        return "***"
    return "*******" + digits[-4:]


def _mask_region(*values: object) -> str | None:
    present = sum(isinstance(value, str) and bool(value.strip()) for value in values)
    return None if present == 0 else "已设置"


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = [
    "PlatformTenantBusinessQueryService",
    "PlatformTenantQueryInputError",
    "PlatformTenantRentalQueryInputError",
    "PlatformTenantRentalQueryService",
]
