"""D48 issue/confirm orchestration for creating an Admin invitation."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

from flask import Request

from app.services.tenant_identity.sensitive_events import (
    build_sensitive_action_security_event as _security_event,
)
from app.services.tenant_identity.sms_runtime import TenantSmsDeliveryRuntime
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase
from inventory_control.domain import Capability
from inventory_control.invitations import (
    AdminInvitationPermissionProof,
    InvitationChallengeRejectedError,
    InvitationPersistenceService,
    InvitationRole,
    derive_admin_invitation_token,
)
from inventory_control.models import TenantSensitiveActionIntent
from inventory_control.sensitive_actions import (
    SensitiveActionContext,
    SensitiveActionIntentService,
)
from inventory_control.sms import CanonicalSmsPhone, SmsPurpose, TrustedSourceBucket
from inventory_control.tenant_http import TenantHttpBoundary

from .support import (
    database_now as _database_now,
    invitation_path as _invitation_path,
    iso as _iso,
    user_phone as _user_phone,
)


class AdminInvitationSensitiveRuntime:
    """Keep Admin-invitation D48 state outside the broad invitation runtime."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_root_key_directory",
        "_trusted_source_resolver",
        "_delivery",
        "_intents",
        "_invitations",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        root_key_directory: str | os.PathLike[str],
        trusted_source_resolver,
        delivery: TenantSmsDeliveryRuntime,
        intent_service: SensitiveActionIntentService,
        invitation_service: InvitationPersistenceService,
    ) -> None:
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._root_key_directory = os.fspath(root_key_directory)
        self._trusted_source_resolver = trusted_source_resolver
        self._delivery = delivery
        self._intents = intent_service
        self._invitations = invitation_service

    def request_challenge(
        self,
        *,
        flask_request: Request,
        target_phone: CanonicalSmsPhone,
        action_uuid: UUID,
    ) -> dict[str, object]:
        source = self._trusted_source_resolver(flask_request)
        if not isinstance(source, TrustedSourceBucket):
            raise RuntimeError("trusted SMS source is unavailable")
        with self._control_database.transaction() as session:
            now = _database_now(session)
            auth = self._tenant_http_boundary.authorize(
                session,
                flask_request,
                capability=Capability.TENANT_MEMBERS_MANAGE,
                now=now,
            )
            actor_phone = _user_phone(session, auth.user_id)
            context = _context(
                tenant_uuid=UUID(auth.tenant_id),
                actor_user_uuid=UUID(auth.user_id),
                actor_session_uuid=UUID(auth.session_id),
                target_phone=target_phone,
                action_uuid=action_uuid,
                tenant_access_version=auth.tenant_access_version,
            )
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).active_key
            prepared = self._intents.prepare_primary(
                session,
                context=context,
                actor_phone=actor_phone,
                trusted_source=source,
                root_key=root_key,
                sms_policy=self._delivery.policy,
                database_now=now,
            )
            if not prepared.replayed:
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=prepared.challenge_uuid,
                        event_type="sensitive_challenge_requested",
                        reason_code="admin_invitation_challenge_requested",
                        safe_outcome="challenge_committed",
                        created_at=now,
                    )
                )

        if prepared.delivery is not None:
            self._delivery.dispatch_committed(prepared.delivery)
        return {
            "intent_id": str(prepared.intent_uuid),
            "challenge_id": str(prepared.challenge_uuid),
            "expires_at": _iso(prepared.expires_at),
            "replayed": prepared.replayed,
        }

    def confirm(
        self,
        *,
        flask_request: Request,
        target_phone: CanonicalSmsPhone,
        action_uuid: UUID,
        challenge_uuid: UUID,
        plaintext_code: object,
    ) -> dict[str, object] | None:
        rejected = False
        with self._control_database.transaction() as session:
            now = _database_now(session)
            auth = self._tenant_http_boundary.authorize(
                session,
                flask_request,
                capability=Capability.TENANT_MEMBERS_MANAGE,
                now=now,
            )
            actor_phone = _user_phone(session, auth.user_id)
            context = _context(
                tenant_uuid=UUID(auth.tenant_id),
                actor_user_uuid=UUID(auth.user_id),
                actor_session_uuid=UUID(auth.session_id),
                target_phone=target_phone,
                action_uuid=action_uuid,
                tenant_access_version=auth.tenant_access_version,
            )
            intent = session.get(TenantSensitiveActionIntent, str(action_uuid))
            if intent is None:
                raise ValueError("sensitive action is unavailable")
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).key_for_existing_reference(intent.root_key_version)
            token = derive_admin_invitation_token(
                root_key=root_key,
                action_uuid=action_uuid,
            )
            authorization = []

            def authorize_admin(current_session, *, database_now):
                verified = self._intents.authorize_primary(
                    current_session,
                    context=context,
                    actor_phone=actor_phone,
                    challenge_uuid=challenge_uuid,
                    plaintext_code=plaintext_code,
                    root_key=root_key,
                    database_now=database_now,
                )
                if not verified.accepted or verified.already_succeeded:
                    raise InvitationChallengeRejectedError()
                assert verified.authorization is not None
                authorization.append(verified.authorization)
                return AdminInvitationPermissionProof(
                    tenant_uuid=context.tenant_uuid,
                    actor_user_uuid=context.actor_user_uuid,
                    actor_session_uuid=context.actor_session_uuid,
                    invitation_uuid=action_uuid,
                    target_phone_e164=target_phone.e164,
                    expected_tenant_access_version=auth.tenant_access_version,
                )

            savepoint = session.begin_nested()
            try:
                result = self._invitations.create_or_resend(
                    session,
                    tenant_uuid=auth.tenant_id,
                    raw_phone=target_phone.e164,
                    role=InvitationRole.ADMIN,
                    proposed_token=token,
                    proposed_invitation_uuid=action_uuid,
                    proposed_user_uuid=uuid4(),
                    expected_tenant_access_version=auth.tenant_access_version,
                    expected_invitation_row_version=None,
                    admin_authorizer=authorize_admin,
                )
                if result.idempotent:
                    replay = self._intents.authorize_primary(
                        session,
                        context=context,
                        actor_phone=actor_phone,
                        challenge_uuid=challenge_uuid,
                        plaintext_code=plaintext_code,
                        root_key=root_key,
                        database_now=now,
                    )
                    if not replay.already_succeeded or result.expires_at <= now:
                        raise ValueError("admin invitation replay is unavailable")
                else:
                    if len(authorization) != 1:
                        raise RuntimeError("admin invitation authorization is missing")
                    self._intents.mark_succeeded(
                        session,
                        authorization=authorization[0],
                        safe_result_code="admin_invitation_created",
                        correlation_id=f"invitation:{result.invitation_uuid}:row:1",
                        database_now=now,
                    )
                    session.add(
                        _security_event(
                            context=context,
                            challenge_uuid=challenge_uuid,
                            event_type="sensitive_challenge_verified",
                            reason_code="admin_invitation_verification_accepted",
                            safe_outcome="verified",
                            created_at=now,
                        )
                    )
                    session.add(
                        _security_event(
                            context=context,
                            challenge_uuid=challenge_uuid,
                            event_type="sensitive_action_committed",
                            reason_code="admin_invitation_created",
                            safe_outcome="succeeded",
                            created_at=now,
                        )
                    )
                savepoint.commit()
            except InvitationChallengeRejectedError:
                if savepoint.is_active:
                    savepoint.rollback()
                retried = self._intents.authorize_primary(
                    session,
                    context=context,
                    actor_phone=actor_phone,
                    challenge_uuid=challenge_uuid,
                    plaintext_code=plaintext_code,
                    root_key=root_key,
                    database_now=now,
                )
                if retried.accepted:
                    raise RuntimeError("sensitive verification rollback failed")
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_challenge_rejected",
                        reason_code="admin_invitation_verification_rejected",
                        safe_outcome="rejected",
                        created_at=now,
                    )
                )
                rejected = True
                result = None
            except Exception:
                if savepoint.is_active:
                    savepoint.rollback()
                raise

        if rejected:
            return None
        assert result is not None
        return {
            "invitation_id": str(result.invitation_uuid),
            "role": result.role.value,
            "status": result.status,
            "token_generation": result.token_generation,
            "expires_at": _iso(result.expires_at),
            "row_version": result.row_version,
            "created": result.created or result.idempotent,
            "rotated": result.rotated,
            "idempotent": result.idempotent,
            "invitation_path": _invitation_path(result),
        }


def _context(
    *,
    tenant_uuid: UUID,
    actor_user_uuid: UUID,
    actor_session_uuid: UUID,
    target_phone: CanonicalSmsPhone,
    action_uuid: UUID,
    tenant_access_version: int,
) -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=action_uuid,
        tenant_uuid=tenant_uuid,
        actor_user_uuid=actor_user_uuid,
        actor_session_uuid=actor_session_uuid,
        purpose=SmsPurpose.ADMIN_INVITATION,
        action_subtype="invitation.create_admin",
        target_type="tenant_invitation",
        target_uuid=action_uuid,
        expected_target_revision="absent",
        action_payload=CanonicalActionPayload.from_value(
            {
                "expected_absent_target": True,
                "role": "admin",
                "target_phone_e164": target_phone.e164,
                "tenant_access_version": tenant_access_version,
                "tenant_uuid": str(tenant_uuid),
            }
        ),
        idempotency_key=f"admin-invitation:{action_uuid}",
    )


__all__ = ["AdminInvitationSensitiveRuntime"]
