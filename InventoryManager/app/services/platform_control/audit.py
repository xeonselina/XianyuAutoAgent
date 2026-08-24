"""One credential-free platform control audit constructor."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from inventory_control.models import PlatformAuditLog
from inventory_control.platform_http import PlatformAuthContext


def build_platform_control_audit(
    *,
    context: PlatformAuthContext,
    route_template: str,
    action: str,
    outcome: str,
    reason_code: str,
    created_at: datetime,
    request_id_prefix: str,
    ip_summary: str | None,
    result_count: int | None,
    target_resource_type: str | None = None,
    target_resource_id: str | None = None,
    target_tenant_id: str | None = None,
    pii_revealed: bool = False,
    authentication_factor: str | None = None,
) -> PlatformAuditLog:
    """Build the fixed platform-admin/control audit projection."""

    if not isinstance(context, PlatformAuthContext):
        raise TypeError("context must be a PlatformAuthContext")
    return PlatformAuditLog(
        actor_type="platform_admin",
        actor_platform_admin_id=context.platform_admin_id,
        actor_platform_session_id=context.session_id,
        target_tenant_id=target_tenant_id,
        target_resource_type=target_resource_type,
        target_resource_id=target_resource_id,
        route_or_command_template=route_template,
        action=action,
        access_mode="control",
        pii_revealed=pii_revealed,
        outcome=outcome,
        safe_reason_code=reason_code,
        authentication_factor=authentication_factor,
        result_count=result_count,
        request_id=f"{request_id_prefix}:{uuid4()}",
        ip_summary=ip_summary,
        created_at=created_at,
    )


__all__ = ["build_platform_control_audit"]
