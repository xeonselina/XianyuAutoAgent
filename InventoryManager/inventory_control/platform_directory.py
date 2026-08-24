"""Minimized control-plane tenant directory for platform administrators."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import Subscription, Tenant, TenantDatabase


_TENANT_STATUSES = frozenset(
    {
        "provisioning",
        "active",
        "expired",
        "suspending",
        "suspended",
        "resuming",
        "deletion_cooling_off",
        "deletion_committing",
        "deleted",
    }
)


class PlatformTenantDirectoryInputError(ValueError):
    pass


class PlatformTenantDirectoryTargetUnavailable(LookupError):
    pass


class PlatformTenantDirectoryService:
    """Read control metadata only; never resolve or open a tenant schema."""

    def list_tenants(
        self,
        session: Session,
        *,
        page: object,
        page_size: object,
        status: object = None,
    ) -> dict[str, object]:
        selected_page = _bounded_integer(page, "page", minimum=1, maximum=100_000)
        selected_size = _bounded_integer(
            page_size, "page_size", minimum=1, maximum=100
        )
        selected_status = _status(status)
        statement = (
            sa.select(
                Tenant.id,
                Tenant.name,
                Tenant.slug,
                Tenant.status,
                Tenant.timezone,
                Tenant.row_version,
                Tenant.updated_at,
                Subscription.status.label("subscription_status"),
                Subscription.expires_at,
                Subscription.row_version.label("subscription_row_version"),
                TenantDatabase.status.label("database_status"),
            )
            .select_from(Tenant)
            .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
            .outerjoin(TenantDatabase, TenantDatabase.tenant_id == Tenant.id)
        )
        if selected_status is not None:
            statement = statement.where(Tenant.status == selected_status)
        rows = session.execute(
            statement.order_by(Tenant.updated_at.desc(), Tenant.id.desc())
            .offset((selected_page - 1) * selected_size)
            .limit(selected_size + 1)
        ).all()
        visible = rows[:selected_size]
        return {
            "items": [
                {
                    "tenant_id": row.id,
                    "name": row.name,
                    "slug": row.slug,
                    "status": row.status,
                    "timezone": row.timezone,
                    "tenant_row_version": row.row_version,
                    "subscription_status": row.subscription_status,
                    "subscription_expires_at": _iso(row.expires_at),
                    "subscription_row_version": row.subscription_row_version,
                    "database_status": row.database_status,
                    "updated_at": _iso(row.updated_at),
                }
                for row in visible
            ],
            "page": selected_page,
            "page_size": selected_size,
            "has_more": len(rows) > selected_size,
            "status_filter": selected_status,
        }

    def get_tenant(
        self,
        session: Session,
        *,
        tenant_id: object,
    ) -> dict[str, object]:
        try:
            selected_id = str(UUID(str(tenant_id)))
        except (TypeError, ValueError, AttributeError):
            raise PlatformTenantDirectoryTargetUnavailable() from None
        row = session.execute(
            sa.select(
                Tenant.id,
                Tenant.name,
                Tenant.slug,
                Tenant.public_identity_published_at,
                Tenant.status,
                Tenant.access_version,
                Tenant.row_version,
                Tenant.timezone,
                Tenant.locale,
                Tenant.created_at,
                Tenant.updated_at,
                Subscription.id.label("subscription_id"),
                Subscription.status.label("subscription_status"),
                Subscription.expires_at,
                Subscription.row_version.label("subscription_row_version"),
                TenantDatabase.database_uuid,
                TenantDatabase.status.label("database_status"),
                TenantDatabase.schema_version,
                TenantDatabase.route_version,
                TenantDatabase.dml_desired_login_state,
                TenantDatabase.dml_observed_login_state,
                TenantDatabase.dml_login_state_version,
                TenantDatabase.platform_read_route_version,
            )
            .select_from(Tenant)
            .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
            .outerjoin(TenantDatabase, TenantDatabase.tenant_id == Tenant.id)
            .where(Tenant.id == selected_id)
        ).one_or_none()
        if row is None:
            raise PlatformTenantDirectoryTargetUnavailable()
        return {
            "tenant_id": row.id,
            "name": row.name,
            "slug": row.slug,
            "public_identity_published_at": _iso(
                row.public_identity_published_at
            ),
            "status": row.status,
            "access_version": row.access_version,
            "tenant_row_version": row.row_version,
            "timezone": row.timezone,
            "locale": row.locale,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "subscription": (
                {
                    "subscription_id": row.subscription_id,
                    "status": row.subscription_status,
                    "expires_at": _iso(row.expires_at),
                    "row_version": row.subscription_row_version,
                }
                if row.subscription_id is not None
                else None
            ),
            "database_route": (
                {
                    "database_uuid": row.database_uuid,
                    "status": row.database_status,
                    "schema_version": row.schema_version,
                    "route_version": row.route_version,
                    "dml_desired_login_state": row.dml_desired_login_state,
                    "dml_observed_login_state": row.dml_observed_login_state,
                    "dml_login_state_version": row.dml_login_state_version,
                    "platform_read_route_version": (
                        row.platform_read_route_version
                    ),
                }
                if row.database_uuid is not None
                else None
            ),
        }


def _bounded_integer(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        raise PlatformTenantDirectoryInputError(f"{field} is invalid") from None
    if isinstance(value, bool) or not minimum <= selected <= maximum:
        raise PlatformTenantDirectoryInputError(f"{field} is invalid")
    if isinstance(value, str) and str(selected) != value:
        raise PlatformTenantDirectoryInputError(f"{field} is invalid")
    return selected


def _status(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in _TENANT_STATUSES:
        raise PlatformTenantDirectoryInputError("status is invalid")
    return value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = [
    "PlatformTenantDirectoryInputError",
    "PlatformTenantDirectoryService",
    "PlatformTenantDirectoryTargetUnavailable",
]
