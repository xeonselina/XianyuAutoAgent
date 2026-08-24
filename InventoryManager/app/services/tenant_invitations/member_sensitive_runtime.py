"""D48 issue/confirm orchestration for tenant Admin membership changes."""

from __future__ import annotations

import os
import re
from uuid import UUID

from flask import Request
import sqlalchemy as sa

from app.services.tenant_identity.sensitive_events import (
    build_sensitive_action_security_event as _security_event,
)
from app.services.tenant_identity.sms_runtime import TenantSmsDeliveryRuntime
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase
from inventory_control.domain import Capability, TenantRole
from inventory_control.identity import (
    AdminPermissionChangeProof,
    MembershipMutationAction,
    TenantMembershipService,
    plan_membership_mutation,
)
from inventory_control.identity.membership_locking import (
    MembershipMutationLocking,
)
from inventory_control.models import (
    TenantMembership,
    TenantSensitiveActionIntent,
)
from inventory_control.sensitive_actions import (
    SensitiveActionContext,
    SensitiveActionIntentService,
)
from inventory_control.sms import CanonicalSmsPhone, SmsPurpose, TrustedSourceBucket
from inventory_control.tenant_http import TenantHttpBoundary

from .support import database_now as _database_now, iso as _iso


_MEMBER_RESULT = re.compile(
    r"membership:([0-9a-f-]{36}):(admin|operator):"
    r"(active|disabled|released):row:([1-9][0-9]*):sessions:([0-9]+)",
    re.ASCII,
)


class MemberSensitiveMutationRuntime:
    """Keep D48 persistence separate from invitation HTTP composition."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_root_key_directory",
        "_trusted_source_resolver",
        "_delivery",
        "_intents",
        "_memberships",
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
        membership_service: TenantMembershipService,
    ) -> None:
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._root_key_directory = os.fspath(root_key_directory)
        self._trusted_source_resolver = trusted_source_resolver
        self._delivery = delivery
        self._intents = intent_service
        self._memberships = membership_service

    def request_challenge(
        self,
        *,
        flask_request: Request,
        membership_uuid: UUID,
        expected_revision: int,
        action: MembershipMutationAction,
        action_uuid: UUID,
        target_role: TenantRole | None,
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
            summary = session.execute(
                sa.select(TenantMembership.user_id).where(
                    TenantMembership.id == str(membership_uuid),
                    TenantMembership.tenant_id == auth.tenant_id,
                )
            ).one_or_none()
            if summary is None:
                raise ValueError("membership is unavailable")
            locked = MembershipMutationLocking.lock(
                session,
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                target_user_id=summary.user_id,
                sensitive_intent_id=str(action_uuid),
                lock_auth_artifacts=False,
            )
            _require_locked_authority(locked, auth=auth)
            target = _locked_target(
                locked,
                membership_uuid=membership_uuid,
                expected_revision=expected_revision,
            )
            plan = plan_membership_mutation(
                current_role=TenantRole(target.role_key),
                current_status=target.status,
                action=action,
                target_role=target_role,
            )
            if not plan.changes_admin_authority or plan.admin_sms_purpose is None:
                raise ValueError("membership action does not require D48")
            context = _context(
                tenant_uuid=UUID(auth.tenant_id),
                actor_user_uuid=UUID(auth.user_id),
                actor_session_uuid=UUID(auth.session_id),
                membership_uuid=membership_uuid,
                expected_revision=expected_revision,
                action=action,
                action_uuid=action_uuid,
                target_role=target_role,
                purpose=SmsPurpose(plan.admin_sms_purpose),
            )
            actor_phone = next(
                CanonicalSmsPhone.from_input(row.phone_e164)
                for row in locked.users
                if row.id == auth.user_id
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
            _require_locked_authority(locked, auth=auth)
            _locked_target(
                locked,
                membership_uuid=membership_uuid,
                expected_revision=expected_revision,
            )
            if not prepared.replayed:
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=prepared.challenge_uuid,
                        event_type="sensitive_challenge_requested",
                        reason_code="member_admin_challenge_requested",
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
        membership_uuid: UUID,
        expected_revision: int,
        action: MembershipMutationAction,
        action_uuid: UUID,
        target_role: TenantRole | None,
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
            summary = session.execute(
                sa.select(TenantMembership.user_id).where(
                    TenantMembership.id == str(membership_uuid),
                    TenantMembership.tenant_id == auth.tenant_id,
                )
            ).one_or_none()
            if summary is None:
                raise ValueError("membership is unavailable")
            locked = MembershipMutationLocking.lock(
                session,
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                target_user_id=summary.user_id,
                sensitive_intent_id=str(action_uuid),
            )
            _require_locked_authority(locked, auth=auth)
            intent = locked.sensitive_intent
            if intent is None:
                raise ValueError("sensitive action is unavailable")
            if intent.status != "succeeded":
                _locked_target(
                    locked,
                    membership_uuid=membership_uuid,
                    expected_revision=expected_revision,
                )
            actor_phone = next(
                CanonicalSmsPhone.from_input(row.phone_e164)
                for row in locked.users
                if row.id == auth.user_id
            )
            context = _context(
                tenant_uuid=UUID(auth.tenant_id),
                actor_user_uuid=UUID(auth.user_id),
                actor_session_uuid=UUID(auth.session_id),
                membership_uuid=membership_uuid,
                expected_revision=expected_revision,
                action=action,
                action_uuid=action_uuid,
                target_role=target_role,
                purpose=SmsPurpose(intent.purpose),
            )
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).key_for_existing_reference(intent.root_key_version)
            verified = self._intents.authorize_primary(
                session,
                context=context,
                actor_phone=actor_phone,
                challenge_uuid=challenge_uuid,
                plaintext_code=plaintext_code,
                root_key=root_key,
                database_now=now,
            )
            if not verified.accepted:
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_challenge_rejected",
                        reason_code="member_admin_verification_rejected",
                        safe_outcome="rejected",
                        created_at=now,
                    )
                )
                rejected = True
                result = None
            elif verified.already_succeeded:
                result = _replayed_member_result(intent)
            else:
                assert verified.authorization is not None
                member = self._memberships.mutate(
                    session,
                    tenant_uuid=UUID(auth.tenant_id),
                    actor_user_uuid=UUID(auth.user_id),
                    actor_membership_uuid=UUID(auth.membership_id),
                    actor_session_uuid=UUID(auth.session_id),
                    target_membership_uuid=membership_uuid,
                    expected_target_revision=expected_revision,
                    action=action,
                    action_uuid=action_uuid,
                    target_role=target_role,
                    admin_proof=AdminPermissionChangeProof(
                        tenant_uuid=UUID(auth.tenant_id),
                        actor_user_uuid=UUID(auth.user_id),
                        actor_session_uuid=UUID(auth.session_id),
                        target_membership_uuid=membership_uuid,
                        expected_target_revision=expected_revision,
                        action=action,
                        target_role=target_role,
                    ),
                    database_now=now,
                )
                result = _member_result(
                    membership_id=str(member.membership_uuid),
                    role=member.role.value,
                    status=member.status,
                    row_version=member.row_version,
                    sessions_revoked=member.sessions_revoked,
                    idempotent=False,
                )
                self._intents.mark_succeeded(
                    session,
                    authorization=verified.authorization,
                    safe_result_code="membership_changed",
                    correlation_id=_correlation(result),
                    database_now=now,
                )
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_challenge_verified",
                        reason_code="member_admin_verification_accepted",
                        safe_outcome="verified",
                        created_at=now,
                    )
                )
                session.add(
                    _security_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_action_committed",
                        reason_code="member_admin_action_committed",
                        safe_outcome="succeeded",
                        created_at=now,
                    )
                )
        return None if rejected else result


def _context(
    *,
    tenant_uuid: UUID,
    actor_user_uuid: UUID,
    actor_session_uuid: UUID,
    membership_uuid: UUID,
    expected_revision: int,
    action: MembershipMutationAction,
    action_uuid: UUID,
    target_role: TenantRole | None,
    purpose: SmsPurpose,
) -> SensitiveActionContext:
    role_value = None if target_role is None else target_role.value
    return SensitiveActionContext(
        intent_uuid=action_uuid,
        tenant_uuid=tenant_uuid,
        actor_user_uuid=actor_user_uuid,
        actor_session_uuid=actor_session_uuid,
        purpose=purpose,
        action_subtype=f"membership.{action.value}",
        target_type="tenant_membership",
        target_uuid=membership_uuid,
        expected_target_revision=f"row:{expected_revision}",
        action_payload=CanonicalActionPayload.from_value(
            {
                "action": action.value,
                "expected_target_revision": expected_revision,
                "target_membership_id": str(membership_uuid),
                "target_role": role_value,
            }
        ),
        idempotency_key=f"membership-admin:{action_uuid}",
    )


def _require_locked_authority(locked, *, auth) -> None:
    actor_user = next(
        (row for row in locked.users if row.id == auth.user_id), None
    )
    actor_membership = next(
        (
            row
            for row in locked.memberships
            if row.id == auth.membership_id
        ),
        None,
    )
    if (
        actor_user is None
        or actor_user.status != "active"
        or actor_membership is None
        or actor_membership.user_id != auth.user_id
        or actor_membership.role_key != "admin"
        or actor_membership.status != "active"
        or locked.tenant.status != "active"
        or locked.tenant.access_version != auth.tenant_access_version
    ):
        raise ValueError("member mutation authority changed")


def _locked_target(locked, *, membership_uuid, expected_revision):
    target = next(
        (
            row
            for row in locked.memberships
            if row.id == str(membership_uuid)
        ),
        None,
    )
    if (
        target is None
        or target.status == "released"
        or target.row_version != expected_revision
    ):
        raise ValueError("membership is unavailable")
    return target


def _member_result(
    *, membership_id, role, status, row_version, sessions_revoked, idempotent
):
    return {
        "membership_id": membership_id,
        "role": role,
        "status": status,
        "row_version": row_version,
        "sessions_revoked": sessions_revoked,
        "idempotent": idempotent,
    }


def _correlation(result: dict[str, object]) -> str:
    return (
        f"membership:{result['membership_id']}:{result['role']}:"
        f"{result['status']}:row:{result['row_version']}:"
        f"sessions:{result['sessions_revoked']}"
    )


def _replayed_member_result(intent: TenantSensitiveActionIntent):
    match = _MEMBER_RESULT.fullmatch(intent.correlation_id or "")
    if match is None or match.group(1) != intent.target_uuid:
        raise RuntimeError("sensitive action result is unavailable")
    return _member_result(
        membership_id=match.group(1),
        role=match.group(2),
        status=match.group(3),
        row_version=int(match.group(4)),
        sessions_revoked=int(match.group(5)),
        idempotent=True,
    )


__all__ = ["MemberSensitiveMutationRuntime"]
