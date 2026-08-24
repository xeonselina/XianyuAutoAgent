"""Transactional control-plane authority for Gantt preview proofs.

The browser ``AuthContext`` is only a lookup-and-comparison snapshot here.  It
never supplies current authorization facts.  Every fact returned by this
adapter is re-read under one explicit control-database transaction, and the
platform root key is selected through the authoritative registry in that same
transaction.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateFacts,
    TenantStatus,
    reduce_tenant_gate,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.identity import (
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.models.subscriptions import Subscription
from inventory_control.models.suspensions import TenantSuspension
from inventory_control.tenant_http import AuthContext

from .gantt_adapter import (
    CurrentGanttPreviewAuthority,
    GanttPreviewAuthorityError,
)
from .gantt_preview import GanttPreviewAuthority


_AUTHORITY_UNAVAILABLE = "current Gantt preview authority is unavailable"


@dataclass(frozen=True, slots=True)
class _ExpectedContext:
    session_uuid: UUID
    user_uuid: UUID
    membership_uuid: UUID
    tenant_uuid: UUID
    role: TenantRole
    user_auth_version: int
    tenant_access_version: int


class SqlAlchemyGanttPreviewAuthorityReader:
    """Re-establish current Gantt authority in one control transaction.

    ``root_key_directory`` is mandatory and has no environment or process
    default.  The directory and its files are verified by
    :class:`SqlAlchemyRootKeyRegistry`; malformed, missing, extra, or
    fingerprint-mismatched entries therefore fail closed.
    """

    __slots__ = ("_control_database", "_root_key_directory")

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_directory: str | os.PathLike[str],
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        try:
            raw_directory = os.fspath(root_key_directory)
        except TypeError:
            raise TypeError("root_key_directory must be an absolute path") from None
        if (
            not isinstance(raw_directory, str)
            or not raw_directory
            or "\x00" in raw_directory
            or not Path(raw_directory).is_absolute()
        ):
            raise ValueError("root_key_directory must be an absolute path")
        self._control_database = control_database
        self._root_key_directory = Path(raw_directory)

    def read_current(
        self,
        *,
        auth_context: AuthContext,
    ) -> CurrentGanttPreviewAuthority:
        """Return only freshly locked and mutually consistent authority facts."""

        try:
            with self.lock_current(auth_context=auth_context) as current:
                return current
        except GanttPreviewAuthorityError:
            raise
        except Exception:
            raise GanttPreviewAuthorityError(_AUTHORITY_UNAVAILABLE) from None

    @contextmanager
    def lock_current(
        self,
        *,
        auth_context: AuthContext,
    ) -> Iterator[CurrentGanttPreviewAuthority]:
        """Yield current facts while retaining the control authority locks."""

        try:
            expected = _expected_context(auth_context)
            transaction = self._control_database.transaction()
            session = transaction.__enter__()
            current = self._read_locked(session, expected=expected)
        except Exception:
            exception = sys.exc_info()
            if "transaction" in locals() and "session" in locals():
                try:
                    transaction.__exit__(*exception)
                except Exception:
                    pass
            raise GanttPreviewAuthorityError(_AUTHORITY_UNAVAILABLE) from None

        try:
            yield current
        except BaseException:
            exception = sys.exc_info()
            try:
                transaction.__exit__(*exception)
            except Exception:
                raise GanttPreviewAuthorityError(_AUTHORITY_UNAVAILABLE) from None
            raise
        else:
            try:
                transaction.__exit__(None, None, None)
            except Exception:
                raise GanttPreviewAuthorityError(_AUTHORITY_UNAVAILABLE) from None

    def _read_locked(
        self,
        session: Session,
        *,
        expected: _ExpectedContext,
    ) -> CurrentGanttPreviewAuthority:
        # Root-key lifecycle writers lock the registry before scanning its
        # references.  Take that prefix first to avoid reversing their order.
        root_key = SqlAlchemyRootKeyRegistry(session=session).load(
            self._root_key_directory
        ).active_key

        # Locate the session without taking its lock, then use the same
        # user -> membership -> tenant/lifecycle -> session order as
        # SessionService.  The final locked session row is the authority.
        located_session = session.scalar(
            sa.select(TenantUserSession)
            .where(TenantUserSession.id == str(expected.session_uuid))
            .execution_options(autoflush=False, populate_existing=True)
        )
        if located_session is None:
            raise ValueError

        user = _exactly_one(
            session,
            sa.select(User)
            .where(User.id == located_session.user_id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        membership = _exactly_one(
            session,
            sa.select(TenantMembership)
            .where(TenantMembership.claimed_user_id == located_session.user_id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        tenant = _exactly_one(
            session,
            sa.select(Tenant)
            .where(Tenant.id == membership.tenant_id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        run = _exactly_one(
            session,
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        hold = _exactly_one(
            session,
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        suspension = _zero_or_one(
            session,
            sa.select(TenantSuspension)
            .where(TenantSuspension.active_tenant_id == tenant.id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        subscription = _exactly_one(
            session,
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant.id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )
        current_session = _exactly_one(
            session,
            sa.select(TenantUserSession)
            .where(TenantUserSession.id == located_session.id)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update(),
        )

        exact_database_now = _database_utc_now(session)
        tenant_timezone = _tenant_timezone(tenant.timezone)
        role = TenantRole(membership.role_key)
        tenant_status = TenantStatus(tenant.status)
        gate = reduce_tenant_gate(
            TenantGateFacts(
                tenant_status=tenant_status,
                current_access_version=tenant.access_version,
                presented_access_version=expected.tenant_access_version,
                recovery_hold_released=(
                    run.status == "completed" and hold.state == "released"
                ),
                unresolved_suspension=suspension is not None,
                subscription_expires_at=_as_utc(subscription.expires_at),
                evaluated_at=exact_database_now,
            )
        )

        if not _matches_current(
            expected=expected,
            located_session=located_session,
            current_session=current_session,
            user=user,
            membership=membership,
            tenant=tenant,
            role=role,
            database_now=exact_database_now,
        ):
            raise ValueError
        if (
            gate.gate is not EffectiveTenantGate.ACTIVE
            or subscription.status != "active"
            or run.status != "completed"
            or hold.state != "released"
        ):
            raise ValueError

        return CurrentGanttPreviewAuthority(
            authority=GanttPreviewAuthority(
                tenant_uuid=_uuid(tenant.id),
                actor_user_uuid=_uuid(user.id),
                actor_session_uuid=_uuid(current_session.id),
                user_auth_version=user.auth_version,
                tenant_access_version=tenant.access_version,
                tenant_timezone=tenant_timezone,
                recovery_run_uuid=_uuid(run.id),
                recovery_hold_uuid=_uuid(hold.id),
                recovery_hold_revision=hold.hold_revision,
            ),
            membership_uuid=_uuid(membership.id),
            role=role,
            session_is_current=True,
            effective_gate=gate.gate,
            active_root_key=root_key,
            database_now=exact_database_now.replace(microsecond=0),
            tenant_timezone=tenant_timezone,
        )

    def __repr__(self) -> str:
        return "SqlAlchemyGanttPreviewAuthorityReader(fail_closed=True)"


def _expected_context(auth_context: AuthContext) -> _ExpectedContext:
    if (
        not isinstance(auth_context, AuthContext)
        or not isinstance(auth_context.role, TenantRole)
        or auth_context.effective_gate is not EffectiveTenantGate.ACTIVE
    ):
        raise ValueError
    return _ExpectedContext(
        session_uuid=_uuid(auth_context.session_id),
        user_uuid=_uuid(auth_context.user_id),
        membership_uuid=_uuid(auth_context.membership_id),
        tenant_uuid=_uuid(auth_context.tenant_id),
        role=auth_context.role,
        user_auth_version=_positive_int(auth_context.user_auth_version),
        tenant_access_version=_positive_int(auth_context.tenant_access_version),
    )


def _matches_current(
    *,
    expected: _ExpectedContext,
    located_session: TenantUserSession,
    current_session: TenantUserSession,
    user: User,
    membership: TenantMembership,
    tenant: Tenant,
    role: TenantRole,
    database_now: datetime,
) -> bool:
    return bool(
        located_session.id == current_session.id
        and located_session.user_id == current_session.user_id
        and _uuid(current_session.id) == expected.session_uuid
        and _uuid(user.id) == expected.user_uuid
        and _uuid(membership.id) == expected.membership_uuid
        and _uuid(tenant.id) == expected.tenant_uuid
        and current_session.user_id == user.id
        and membership.user_id == user.id
        and membership.claimed_user_id == user.id
        and membership.tenant_id == tenant.id
        and user.status == "active"
        and membership.status == "active"
        and membership.released_at is None
        and current_session.revoked_at is None
        and current_session.auth_version_at_issue == user.auth_version
        and current_session.tenant_access_version_at_issue
        == tenant.access_version
        and expected.user_auth_version == user.auth_version
        and expected.tenant_access_version == tenant.access_version
        and expected.role is role
        and _as_utc(current_session.idle_expires_at) > database_now
        and _as_utc(current_session.absolute_expires_at) > database_now
    )


def _exactly_one(session: Session, statement):
    rows = tuple(session.scalars(statement))
    if len(rows) != 1:
        raise ValueError
    return rows[0]


def _zero_or_one(session: Session, statement):
    rows = tuple(session.scalars(statement))
    if len(rows) > 1:
        raise ValueError
    return rows[0] if rows else None


def _database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tenant_timezone(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError
    zone = ZoneInfo(value)
    if zone.key != value:
        raise ValueError
    return value


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


__all__ = ["SqlAlchemyGanttPreviewAuthorityReader"]
