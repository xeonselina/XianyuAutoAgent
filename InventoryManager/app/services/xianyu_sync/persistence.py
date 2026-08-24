"""Short-transaction application of independently obtained Xianyu results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.rental import Rental
from app.models.xianyu_order_alert import (
    XianyuConnectionSyncState,
    XianyuOrderAlert,
    XianyuOrderSyncState,
)

from .contracts import (
    XianyuAlertFact,
    XianyuConnectionRef,
    XianyuConnectionSyncResult,
    XianyuSyncInputError,
)


class XianyuSyncConflict(RuntimeError):
    """A different durable job already owns this tenant synchronization."""


@dataclass(frozen=True, slots=True)
class XianyuSyncApplyResult:
    snapshot_revision: int
    sync_status: str
    applied: bool


class XianyuSyncPersistenceService:
    """Persist one tenant job without performing control or provider I/O.

    The caller owns and commits the tenant transaction.  Provider calls must be
    completed before ``apply_results`` is entered, so this service can never
    hold a tenant connection across network I/O.
    """

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def mark_started(
        self,
        *,
        job_uuid: str,
        connections: tuple[XianyuConnectionRef, ...],
        attempted_at: datetime,
    ) -> XianyuSyncApplyResult:
        self._require_transaction()
        job_id = _uuid(job_uuid)
        attempted = _naive_utc(attempted_at)
        _unique_connections(connections)
        aggregate = self._aggregate_for_update()
        if aggregate.last_applied_job_uuid == job_id:
            return _result(aggregate, applied=False)
        if (
            aggregate.current_job_uuid is not None
            and aggregate.current_job_uuid != job_id
            and aggregate.sync_status == "syncing"
        ):
            raise XianyuSyncConflict("another Xianyu job is already active")

        aggregate.current_job_uuid = job_id
        aggregate.sync_status = "syncing"
        aggregate.last_attempt_at = attempted
        aggregate.updated_at = attempted
        for connection in connections:
            state = self._connection_for_update(connection.integration_uuid)
            if state is None:
                state = XianyuConnectionSyncState(
                    integration_uuid=connection.integration_uuid,
                    secret_revision_uuid=connection.secret_revision_uuid,
                    sync_status="syncing",
                    last_job_uuid=job_id,
                    last_attempt_at=attempted,
                    created_at=attempted,
                    updated_at=attempted,
                )
                self._session.add(state)
                continue
            if (
                state.sync_status == "syncing"
                and state.last_job_uuid not in (None, job_id)
            ):
                raise XianyuSyncConflict(
                    "another job owns a Xianyu connection"
                )
            if state.secret_revision_uuid != connection.secret_revision_uuid:
                # Provider cursors are credential/connection revision scoped.
                # Never reuse one after a credential rotation, even when the
                # first attempt under the new revision later fails.
                state.provider_cursor = None
            state.secret_revision_uuid = connection.secret_revision_uuid
            state.sync_status = "syncing"
            state.last_job_uuid = job_id
            state.last_attempt_at = attempted
            state.safe_error_code = None
            state.retry_after_at = None
            state.row_version = int(state.row_version or 0) + 1
            state.updated_at = attempted
        self._session.flush()
        return _result(aggregate, applied=True)

    def apply_results(
        self,
        *,
        job_uuid: str,
        results: tuple[XianyuConnectionSyncResult, ...],
        completed_at: datetime,
    ) -> XianyuSyncApplyResult:
        self._require_transaction()
        job_id = _uuid(job_uuid)
        completed = _naive_utc(completed_at)
        _unique_results(results)
        aggregate = self._aggregate_for_update()
        if aggregate.last_applied_job_uuid == job_id:
            return _result(aggregate, applied=False)
        if aggregate.current_job_uuid != job_id:
            raise XianyuSyncConflict("result does not own the active Xianyu job")

        expected = {
            row.integration_uuid: row
            for row in self._session.scalars(
                sa.select(XianyuConnectionSyncState)
                .where(
                    XianyuConnectionSyncState.last_job_uuid == job_id,
                    XianyuConnectionSyncState.sync_status == "syncing",
                )
                .order_by(XianyuConnectionSyncState.integration_uuid.asc())
                .with_for_update()
            )
        }
        supplied = {result.integration_uuid for result in results}
        if expected and set(expected) != supplied:
            raise XianyuSyncConflict("connection result set is incomplete")

        successful = 0
        for connection_result in results:
            state = expected.get(connection_result.integration_uuid)
            if state is None:
                state = self._connection_for_update(
                    connection_result.integration_uuid
                )
            if state is None:
                state = XianyuConnectionSyncState(
                    integration_uuid=connection_result.integration_uuid,
                    secret_revision_uuid=connection_result.secret_revision_uuid,
                    created_at=completed,
                )
                self._session.add(state)
            elif (
                state.last_job_uuid == job_id
                and state.secret_revision_uuid
                != connection_result.secret_revision_uuid
            ):
                raise XianyuSyncConflict(
                    "connection credential revision changed within a job"
                )

            state.secret_revision_uuid = connection_result.secret_revision_uuid
            state.last_job_uuid = job_id
            state.last_attempt_at = completed
            state.sync_status = connection_result.status
            state.safe_error_code = connection_result.safe_error_code
            state.retry_after_at = (
                _naive_utc(connection_result.retry_after_at)
                if connection_result.retry_after_at is not None
                else None
            )
            state.row_version = int(state.row_version or 0) + 1
            state.updated_at = completed
            if connection_result.status == "succeeded":
                successful += 1
                self._replace_connection_alerts(
                    result=connection_result,
                    seen_at=completed,
                )
                state.last_success_at = completed
                state.snapshot_revision = int(state.snapshot_revision or 0) + 1
                state.provider_cursor = connection_result.provider_cursor

        aggregate.snapshot_revision = int(aggregate.snapshot_revision or 0) + 1
        aggregate.last_applied_job_uuid = job_id
        aggregate.current_job_uuid = None
        aggregate.last_attempt_at = completed
        aggregate.updated_at = completed
        if successful == len(results):
            aggregate.sync_status = "succeeded"
            aggregate.last_success_at = completed
            aggregate.last_error = None
        elif successful:
            aggregate.sync_status = "partial_failure"
            aggregate.last_success_at = completed
            aggregate.last_error = "部分闲鱼连接同步失败"
        elif all(result.status == "rate_limited" for result in results):
            aggregate.sync_status = "rate_limited"
            aggregate.last_error = "闲鱼同步受到频率限制"
        else:
            aggregate.sync_status = "failed"
            aggregate.last_error = "闲鱼订单查询失败"
        self._session.flush()
        return _result(aggregate, applied=True)

    def _replace_connection_alerts(
        self,
        *,
        result: XianyuConnectionSyncResult,
        seen_at: datetime,
    ) -> None:
        existing_rentals = {
            str(order_no).strip()
            for order_no in self._session.scalars(
                sa.select(Rental.xianyu_order_no).where(
                    Rental.xianyu_order_no.is_not(None)
                )
            )
            if order_no and str(order_no).strip()
        }
        ignored = set(
            self._session.scalars(
                sa.select(XianyuOrderAlert.order_no).where(
                    XianyuOrderAlert.state == "ignored"
                )
            )
        )
        supplied = {
            alert.order_no: alert
            for alert in result.alerts
            if alert.order_no not in existing_rentals
            and alert.order_no not in ignored
        }
        current = {
            alert.order_no: alert
            for alert in self._session.scalars(
                sa.select(XianyuOrderAlert)
                .where(
                    XianyuOrderAlert.state == "pending",
                    XianyuOrderAlert.integration_uuid
                    == result.integration_uuid,
                )
                .order_by(XianyuOrderAlert.id.asc())
                .with_for_update()
            )
        }
        for order_no, alert in current.items():
            if order_no not in supplied:
                self._session.delete(alert)

        all_existing = (
            {
                alert.order_no: alert
                for alert in self._session.scalars(
                    sa.select(XianyuOrderAlert)
                    .where(XianyuOrderAlert.order_no.in_(tuple(supplied)))
                    .order_by(XianyuOrderAlert.id.asc())
                    .with_for_update()
                )
            }
            if supplied
            else {}
        )
        for order_no, fact in supplied.items():
            alert = all_existing.get(order_no)
            if alert is not None and alert.integration_uuid not in (
                None,
                result.integration_uuid,
            ):
                # Xianyu order numbers are globally deduplicated in the legacy
                # schema.  Preserve the first owner instead of allowing one
                # connection to overwrite another connection's snapshot.
                continue
            if alert is None:
                alert = XianyuOrderAlert(
                    order_no=order_no,
                    state="pending",
                    pay_amount=fact.pay_amount,
                    first_detected_at=seen_at,
                    created_at=seen_at,
                )
                self._session.add(alert)
            alert.integration_uuid = result.integration_uuid
            alert.secret_revision_uuid = result.secret_revision_uuid
            alert.pay_amount = fact.pay_amount
            alert.buyer_nick = fact.buyer_nick
            alert.receiver_name = fact.receiver_name
            alert.receiver_mobile = fact.receiver_mobile
            alert.address = fact.address
            alert.goods_title = fact.goods_title
            alert.goods_sku_text = fact.goods_sku_text
            alert.order_time = (
                _naive_utc(fact.order_time)
                if fact.order_time is not None
                else None
            )
            alert.last_seen_at = seen_at
            alert.updated_at = seen_at

    def _aggregate_for_update(self) -> XianyuOrderSyncState:
        state = self._session.scalar(
            sa.select(XianyuOrderSyncState)
            .where(XianyuOrderSyncState.id == 1)
            .with_for_update()
        )
        if state is None:
            state = XianyuOrderSyncState(id=1)
            self._session.add(state)
            self._session.flush()
        return state

    def _connection_for_update(
        self, integration_uuid: str
    ) -> XianyuConnectionSyncState | None:
        return self._session.scalar(
            sa.select(XianyuConnectionSyncState)
            .where(
                XianyuConnectionSyncState.integration_uuid
                == integration_uuid
            )
            .with_for_update()
        )

    def _require_transaction(self) -> None:
        if not self._session.in_transaction():
            raise RuntimeError("an explicit tenant transaction is required")


def _result(
    aggregate: XianyuOrderSyncState, *, applied: bool
) -> XianyuSyncApplyResult:
    return XianyuSyncApplyResult(
        snapshot_revision=int(aggregate.snapshot_revision or 0),
        sync_status=aggregate.sync_status,
        applied=applied,
    )


def _unique_connections(connections: tuple[XianyuConnectionRef, ...]) -> None:
    if not isinstance(connections, tuple) or not connections or any(
        not isinstance(connection, XianyuConnectionRef)
        for connection in connections
    ):
        raise XianyuSyncInputError("connections are invalid")
    identifiers = [connection.integration_uuid for connection in connections]
    if len(identifiers) != len(set(identifiers)):
        raise XianyuSyncInputError("connections contain duplicates")


def _unique_results(results: tuple[XianyuConnectionSyncResult, ...]) -> None:
    if not isinstance(results, tuple) or not results or any(
        not isinstance(result, XianyuConnectionSyncResult)
        for result in results
    ):
        raise XianyuSyncInputError("results are invalid")
    identifiers = [result.integration_uuid for result in results]
    if len(identifiers) != len(set(identifiers)):
        raise XianyuSyncInputError("results contain duplicates")


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise XianyuSyncInputError("identifier is invalid") from None


def _naive_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise XianyuSyncInputError("timestamp is invalid")
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
