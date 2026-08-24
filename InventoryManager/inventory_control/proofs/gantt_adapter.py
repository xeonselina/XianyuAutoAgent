"""Fail-closed SaaS adapter for Gantt reorder preview proofs.

The pure proof codec deliberately knows nothing about Flask sessions or the
control database. This adapter bridges those domains through one required
current-read port. There is intentionally no environment/configuration
fallback: a caller that cannot prove the current tenant session, recovery
state, database time, and active platform root key cannot issue or verify a
SaaS proof.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import ContextManager, Iterator, Protocol, runtime_checkable
from uuid import UUID
from zoneinfo import ZoneInfo

from inventory_control.crypto import RootKey
from inventory_control.domain.access_policy import (
    has_tenant_capability_for_gate,
)
from inventory_control.domain.rbac import Capability, TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.tenant_http import AuthContext

from .gantt_preview import (
    GANTT_PREVIEW_MAX_TTL_SECONDS,
    GanttPreviewAuthority,
    GanttPreviewContent,
    GanttPreviewProofError,
    VerifiedGanttPreview,
    issue_gantt_preview_proof,
    verify_gantt_preview_proof,
)


class GanttPreviewAuthorityError(GanttPreviewProofError):
    """The current trusted SaaS authority could not be established."""


class GanttPreviewFenceReleaseUncertain(GanttPreviewProofError):
    """Tenant work completed but releasing its control fence was uncertain."""

    def __init__(self) -> None:
        super().__init__(
            "Gantt preview authority fence release is uncertain"
        )


@dataclass(frozen=True, slots=True)
class CurrentGanttPreviewAuthority:
    """One atomic current-read result from the control plane.

    ``active_root_key`` must be the sole active version selected from the
    authoritative root-key registry. ``database_now`` and every authority
    field must come from the same current control-plane read, rather than from
    browser input or process-local defaults.
    """

    authority: GanttPreviewAuthority
    membership_uuid: UUID
    role: TenantRole
    session_is_current: bool
    effective_gate: EffectiveTenantGate
    active_root_key: RootKey
    database_now: datetime
    tenant_timezone: str


@runtime_checkable
class GanttPreviewCurrentAuthorityReader(Protocol):
    """Read all current proof authority for one already authenticated actor."""

    def read_current(
        self,
        *,
        auth_context: AuthContext,
    ) -> CurrentGanttPreviewAuthority:
        ...

    def lock_current(
        self,
        *,
        auth_context: AuthContext,
    ) -> ContextManager[CurrentGanttPreviewAuthority]:
        """Hold the current control authority fence until context exit."""

        ...


class GanttPreviewProofAdapter:
    """Issue and verify Gantt proofs only from explicit current SaaS authority."""

    __slots__ = ("_authority_reader",)

    def __init__(
        self,
        *,
        authority_reader: GanttPreviewCurrentAuthorityReader,
    ) -> None:
        if not isinstance(authority_reader, GanttPreviewCurrentAuthorityReader):
            raise TypeError(
                "authority_reader must implement GanttPreviewCurrentAuthorityReader"
            )
        self._authority_reader = authority_reader

    def issue(
        self,
        *,
        auth_context: AuthContext,
        content: GanttPreviewContent,
        ttl: timedelta = timedelta(
            seconds=GANTT_PREVIEW_MAX_TTL_SECONDS
        ),
    ) -> str:
        """Issue a proof from a fresh active-session authority snapshot."""

        if not isinstance(content, GanttPreviewContent):
            raise TypeError("content must be a GanttPreviewContent")
        current = self._read_current(auth_context)
        _require_current_business_date(content, current)
        return issue_gantt_preview_proof(
            root_key=current.active_root_key,
            authority=current.authority,
            content=content,
            database_now=current.database_now,
            ttl=ttl,
        )

    def require_current(self, *, auth_context: AuthContext) -> None:
        """Fail before tenant data access unless current SaaS authority exists."""

        self._read_current(auth_context)

    def current_business_date(
        self,
        *,
        auth_context: AuthContext,
    ) -> date:
        """Return the tenant-local date derived from current database time."""

        return _current_business_date(self._read_current(auth_context))

    def verify(
        self,
        *,
        auth_context: AuthContext,
        token: object,
    ) -> VerifiedGanttPreview:
        """Verify against newly read session, gate, recovery, and key facts."""

        current = self._read_current(auth_context)
        verified = verify_gantt_preview_proof(
            token=token,
            root_key=current.active_root_key,
            expected_authority=current.authority,
            database_now=current.database_now,
        )
        _require_current_business_date(verified.content, current)
        return verified

    @contextmanager
    def verify_for_execution(
        self,
        *,
        auth_context: AuthContext,
        token: object,
    ) -> Iterator[VerifiedGanttPreview]:
        """Verify while holding the control-plane tenant authority fence.

        The caller may commit or roll back its already-open tenant-database
        transaction inside the yielded scope.  This context owns no tenant
        transaction; it only keeps the control ``Tenant`` and related current
        authority rows locked so a lifecycle transition cannot race the
        verified tenant commit.
        """

        _require_active_rental_actor(auth_context)
        try:
            manager = self._authority_reader.lock_current(
                auth_context=auth_context
            )
            current = manager.__enter__()
        except Exception:
            raise GanttPreviewAuthorityError(
                "current Gantt preview authority is unavailable"
            ) from None

        try:
            current = self._validate_current(auth_context, current)
            verified = verify_gantt_preview_proof(
                token=token,
                root_key=current.active_root_key,
                expected_authority=current.authority,
                database_now=current.database_now,
            )
            _require_current_business_date(verified.content, current)
        except BaseException:
            exception = sys.exc_info()
            try:
                manager.__exit__(*exception)
            except Exception:
                raise GanttPreviewAuthorityError(
                    "current Gantt preview authority is unavailable"
                ) from None
            raise

        try:
            yield verified
        except BaseException:
            exception = sys.exc_info()
            try:
                manager.__exit__(*exception)
            except Exception:
                # The caller's tenant operation already failed.  Preserve that
                # primary error; the control transaction's own context is
                # responsible for rolling back its unit of work.
                pass
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                raise GanttPreviewFenceReleaseUncertain() from None

    def _read_current(
        self,
        auth_context: AuthContext,
    ) -> CurrentGanttPreviewAuthority:
        _require_active_rental_actor(auth_context)
        try:
            current = self._authority_reader.read_current(
                auth_context=auth_context
            )
        except Exception:
            raise GanttPreviewAuthorityError(
                "current Gantt preview authority is unavailable"
            ) from None
        return self._validate_current(auth_context, current)

    def _validate_current(
        self,
        auth_context: AuthContext,
        current: object,
    ) -> CurrentGanttPreviewAuthority:
        if not isinstance(current, CurrentGanttPreviewAuthority):
            raise GanttPreviewAuthorityError(
                "current Gantt preview authority is unavailable"
            )
        if (
            not isinstance(current.authority, GanttPreviewAuthority)
            or not isinstance(current.membership_uuid, UUID)
            or not isinstance(current.role, TenantRole)
            or current.session_is_current is not True
            or current.effective_gate is not EffectiveTenantGate.ACTIVE
            or not isinstance(current.active_root_key, RootKey)
            or current.tenant_timezone != current.authority.tenant_timezone
        ):
            raise GanttPreviewAuthorityError(
                "current Gantt preview authority is unavailable"
            )
        _match_auth_context(auth_context, current.authority)
        if (
            UUID(auth_context.membership_id) != current.membership_uuid
            or auth_context.role is not current.role
        ):
            raise GanttPreviewAuthorityError(
                "current Gantt preview authority is unavailable"
            )
        _current_business_date(current)
        return current


def _require_active_rental_actor(auth_context: AuthContext) -> None:
    if not isinstance(auth_context, AuthContext):
        raise GanttPreviewAuthorityError(
            "current Gantt preview authority is unavailable"
        )
    if (
        not isinstance(auth_context.role, TenantRole)
        or auth_context.effective_gate is not EffectiveTenantGate.ACTIVE
        or isinstance(auth_context.user_auth_version, bool)
        or not isinstance(auth_context.user_auth_version, int)
        or auth_context.user_auth_version < 1
        or isinstance(auth_context.tenant_access_version, bool)
        or not isinstance(auth_context.tenant_access_version, int)
        or auth_context.tenant_access_version < 1
        or not has_tenant_capability_for_gate(
            role=auth_context.role,
            gate=auth_context.effective_gate,
            capability=Capability.RENTAL_WRITE,
        )
    ):
        raise GanttPreviewAuthorityError(
            "current Gantt preview authority is unavailable"
        )
    try:
        UUID(auth_context.membership_id)
        UUID(auth_context.tenant_id)
        UUID(auth_context.user_id)
        UUID(auth_context.session_id)
    except (AttributeError, TypeError, ValueError):
        raise GanttPreviewAuthorityError(
            "current Gantt preview authority is unavailable"
        ) from None


def _match_auth_context(
    auth_context: AuthContext,
    authority: GanttPreviewAuthority,
) -> None:
    try:
        matches = (
            UUID(auth_context.tenant_id) == authority.tenant_uuid
            and UUID(auth_context.user_id) == authority.actor_user_uuid
            and UUID(auth_context.session_id) == authority.actor_session_uuid
            and auth_context.user_auth_version == authority.user_auth_version
            and auth_context.tenant_access_version
            == authority.tenant_access_version
        )
    except (AttributeError, TypeError, ValueError):
        matches = False
    if not matches:
        raise GanttPreviewAuthorityError(
            "current Gantt preview authority is unavailable"
        )


def _current_business_date(current: CurrentGanttPreviewAuthority) -> date:
    try:
        database_now = current.database_now
        if (
            not isinstance(database_now, datetime)
            or database_now.tzinfo is None
            or database_now.utcoffset() is None
            or database_now.microsecond != 0
            or not isinstance(current.tenant_timezone, str)
            or not current.tenant_timezone
        ):
            raise ValueError
        zone = ZoneInfo(current.tenant_timezone)
        if zone.key != current.tenant_timezone:
            raise ValueError
        return database_now.astimezone(zone).date()
    except Exception:
        raise GanttPreviewAuthorityError(
            "current Gantt preview authority is unavailable"
        ) from None


def _require_current_business_date(
    content: GanttPreviewContent,
    current: CurrentGanttPreviewAuthority,
) -> None:
    if content.preview_date != _current_business_date(current):
        raise GanttPreviewProofError("preview proof is invalid or stale")


__all__ = [
    "CurrentGanttPreviewAuthority",
    "GanttPreviewAuthorityError",
    "GanttPreviewCurrentAuthorityReader",
    "GanttPreviewFenceReleaseUncertain",
    "GanttPreviewProofAdapter",
]
