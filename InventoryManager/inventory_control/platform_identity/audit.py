"""SQLAlchemy adapter for credential-free platform login audit events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from inventory_control.models import PlatformAuditLog

from .login_service import PlatformLoginAuditEvent
from .step_up_service import PlatformStepUpAuditEvent


class SqlAlchemyPlatformLoginAuditRecorder:
    """Append one immutable row without committing the caller transaction."""

    def record(
        self,
        session: Session,
        *,
        event: PlatformLoginAuditEvent,
    ) -> None:
        if not isinstance(session, Session) or not isinstance(
            event, PlatformLoginAuditEvent
        ):
            raise TypeError("platform login audit input is invalid")
        succeeded = event.outcome == "succeeded"
        session.add(
            PlatformAuditLog(
                actor_type="platform_admin" if succeeded else "system",
                actor_platform_admin_id=(
                    event.platform_admin_id if succeeded else None
                ),
                actor_platform_session_id=(
                    event.platform_session_id if succeeded else None
                ),
                target_platform_admin_id=event.platform_admin_id,
                route_or_command_template="POST /platform/api/login",
                action="platform.login",
                access_mode="authentication",
                pii_revealed=False,
                outcome=event.outcome,
                safe_reason_code=(
                    f"platform_login.{event.stage}.{event.outcome}"
                ),
                authentication_factor=event.factor_method,
                request_id=event.request_id,
                created_at=event.occurred_at,
            )
        )
        session.flush()


class SqlAlchemyPlatformStepUpAuditRecorder:
    """Persist a credential-free recent-MFA session-rotation event."""

    def record(
        self,
        session: Session,
        *,
        event: PlatformStepUpAuditEvent,
    ) -> None:
        if not isinstance(session, Session) or not isinstance(
            event, PlatformStepUpAuditEvent
        ):
            raise TypeError("platform step-up audit input is invalid")
        session.add(
            PlatformAuditLog(
                actor_type="platform_admin",
                actor_platform_admin_id=event.platform_admin_id,
                actor_platform_session_id=event.actor_session_id,
                target_platform_admin_id=event.platform_admin_id,
                target_resource_type=(
                    "platform_session"
                    if event.replacement_session_id is not None
                    else None
                ),
                target_resource_id=event.replacement_session_id,
                route_or_command_template="POST /platform/api/step-up",
                action="platform.step_up",
                access_mode="authentication",
                pii_revealed=False,
                outcome=event.outcome,
                safe_reason_code=f"platform_step_up.{event.outcome}",
                authentication_factor=event.factor_method,
                result_count=1 if event.outcome == "succeeded" else 0,
                request_id=event.request_id,
                created_at=event.occurred_at,
            )
        )
        session.flush()


__all__ = [
    "SqlAlchemyPlatformLoginAuditRecorder",
    "SqlAlchemyPlatformStepUpAuditRecorder",
]
