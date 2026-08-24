"""Shared payload-free security-event construction for D48 actions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from inventory_control.models import TenantAuthSecurityEvent
from inventory_control.sensitive_actions import SensitiveActionContext


def build_sensitive_action_security_event(
    *,
    context: SensitiveActionContext,
    challenge_uuid: UUID,
    event_type: str,
    reason_code: str,
    safe_outcome: str,
    created_at: datetime,
) -> TenantAuthSecurityEvent:
    """Build the fixed metadata-only event shared by D48 HTTP runtimes."""

    return TenantAuthSecurityEvent(
        tenant_id=str(context.tenant_uuid),
        user_id=str(context.actor_user_uuid),
        actor_session_id=str(context.actor_session_uuid),
        target_session_id=None,
        target_resource_type=context.target_type,
        target_resource_id=str(context.target_uuid),
        expected_target_revision=context.expected_target_revision,
        challenge_id=str(challenge_uuid),
        intent_id=str(context.intent_uuid),
        action_subtype=context.action_subtype,
        idempotency_reference=context.idempotency_key,
        safe_outcome=safe_outcome,
        event_type=event_type,
        reason_code=reason_code,
        request_id=f"sensitive-action:{context.intent_uuid}",
        created_at=created_at,
    )


__all__ = ["build_sensitive_action_security_event"]
