"""Local-only Xianyu alert snapshots for tenant HTTP reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.rental import Rental
from app.models.xianyu_order_alert import (
    XianyuConnectionSyncState,
    XianyuOrderAlert,
    XianyuOrderSyncState,
)


_STALE_AFTER = timedelta(seconds=360)


class XianyuAlertQueryInputError(ValueError):
    pass


class XianyuAlertNotFound(LookupError):
    pass


class XianyuAlertSnapshotQueryService:
    """Read or mutate cached tenant facts without any provider dependency."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def get_snapshot(self, *, database_now: datetime) -> dict[str, object]:
        now = _aware_utc(database_now)
        recorded_orders = {
            str(value).strip()
            for value in self._session.scalars(
                sa.select(Rental.xianyu_order_no).where(
                    Rental.xianyu_order_no.is_not(None)
                )
            )
            if value and str(value).strip()
        }
        alerts = [
            row.to_dict()
            for row in self._session.scalars(
                sa.select(XianyuOrderAlert)
                .where(XianyuOrderAlert.state == "pending")
                .order_by(
                    XianyuOrderAlert.order_time.desc(),
                    XianyuOrderAlert.id.desc(),
                )
            )
            if row.order_no not in recorded_orders
        ]
        aggregate = self._session.get(XianyuOrderSyncState, 1)
        connection_states = tuple(
            self._session.scalars(
                sa.select(XianyuConnectionSyncState).order_by(
                    XianyuConnectionSyncState.integration_uuid.asc()
                )
            )
        )
        sync = (
            aggregate.to_dict()
            if aggregate is not None
            else {
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error": None,
                "snapshot_revision": 0,
                "sync_status": "never",
                "current_job_uuid": None,
            }
        )
        last_success = (
            None
            if aggregate is None
            else _optional_aware_utc(aggregate.last_success_at)
        )
        stale = last_success is None or now - last_success > _STALE_AFTER
        return {
            "alerts": alerts,
            "count": len(alerts),
            "snapshot_revision": int(sync["snapshot_revision"]),
            "last_successful_sync_at": sync["last_success_at"],
            "sync_status": sync["sync_status"],
            "stale": stale,
            "refreshing": bool(
                aggregate is not None
                and aggregate.sync_status == "syncing"
                and aggregate.current_job_uuid is not None
            ),
            "sync": sync,
            "connection_statuses": [
                {
                    "integration_uuid": state.integration_uuid,
                    "sync_status": state.sync_status,
                    "last_successful_sync_at": XianyuOrderAlert._iso(
                        state.last_success_at
                    ),
                    "safe_error_code": state.safe_error_code,
                    "retry_after_at": XianyuOrderAlert._iso(
                        state.retry_after_at
                    ),
                }
                for state in connection_states
            ],
        }

    def get_snapshot_revision(self) -> int:
        """Return only the aggregate marker needed by refresh submission."""

        value = self._session.scalar(
            sa.select(XianyuOrderSyncState.snapshot_revision).where(
                XianyuOrderSyncState.id == 1
            )
        )
        return int(value or 0)

    def ignore(
        self,
        *,
        order_no: str,
        reason: str,
        ignored_at: datetime,
    ) -> None:
        self._require_transaction()
        normalized_order = _text(order_no, maximum=50, field="order_no")
        normalized_reason = _text(reason, maximum=500, field="reason")
        alert = self._session.scalar(
            sa.select(XianyuOrderAlert)
            .where(
                XianyuOrderAlert.order_no == normalized_order,
                XianyuOrderAlert.state == "pending",
            )
            .with_for_update()
        )
        if alert is None:
            raise XianyuAlertNotFound("待处理订单不存在")
        when = _naive_utc(ignored_at)
        alert.state = "ignored"
        alert.ignored_reason = normalized_reason
        alert.ignored_at = when
        alert.updated_at = when
        self._session.flush()

    def _require_transaction(self) -> None:
        if not self._session.in_transaction():
            raise RuntimeError("an explicit tenant transaction is required")


def _text(value: object, *, maximum: int, field: str) -> str:
    if not isinstance(value, str):
        raise XianyuAlertQueryInputError(f"{field} is invalid")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise XianyuAlertQueryInputError(f"{field} is invalid")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise XianyuAlertQueryInputError("database_now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _aware_utc(value).replace(tzinfo=None)
