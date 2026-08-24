"""HTTP-facing D47/D48 orchestration for self-service phone changes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

from flask import Request
import sqlalchemy as sa

from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKeyLoadError, SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.identity import (
    PhoneChangeAuthorizationProof,
    PhoneChangeConflictError,
    PhoneChangeInputError,
    TenantPhoneChangeService,
)
from inventory_control.models import TenantSensitiveActionIntent, User
from inventory_control.sensitive_actions import (
    SensitiveActionConflictError,
    SensitiveActionContext,
    SensitiveActionInputError,
    SensitiveActionIntentService,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsSendRejected,
    SmsPurpose,
    TrustedSourceBucket,
)
from inventory_control.tenant_http import TenantHttpBoundary, TenantHttpError

from .sensitive_events import build_sensitive_action_security_event
from .sms_runtime import TenantSmsDeliveryRuntime


class TenantPhoneChangeInputRejected(TenantHttpError):
    status_code = 400
    code = "PHONE_CHANGE_INPUT_INVALID"
    public_message = "手机号变更请求格式无效。"


class TenantPhoneChangeVerificationRejected(TenantHttpError):
    status_code = 403
    code = "PHONE_CHANGE_VERIFICATION_REJECTED"
    public_message = "旧号码和新号码验证码必须在同一次变更中完成验证。"


class TenantPhoneChangeConflict(TenantHttpError):
    status_code = 409
    code = "PHONE_CHANGE_CONFLICT"
    public_message = "手机号归属或账号状态已变化，请重新发起变更。"


class TenantPhoneChangeRuntime:
    """Keep dual-code delivery and final phone ownership in one boundary."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_root_key_directory",
        "_trusted_source_resolver",
        "_delivery",
        "_intents",
        "_phones",
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
        phone_change_service: TenantPhoneChangeService | None = None,
    ) -> None:
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._root_key_directory = os.fspath(root_key_directory)
        self._trusted_source_resolver = trusted_source_resolver
        self._delivery = delivery
        self._intents = intent_service
        self._phones = phone_change_service or TenantPhoneChangeService()

    def request_challenges(
        self,
        *,
        flask_request: Request,
        raw_new_phone: object,
        action_id: object,
    ) -> dict[str, object]:
        new_phone = _phone(raw_new_phone)
        action_uuid = _uuid(action_id)
        source = self._trusted_source_resolver(flask_request)
        if not isinstance(source, TrustedSourceBucket):
            raise RuntimeError("trusted SMS source is unavailable")
        with self._control_database.transaction() as session:
            now = _database_now(session)
            auth = self._tenant_http_boundary.authorize(
                session,
                flask_request,
                capability=Capability.PHONE_SELF_CHANGE,
                now=now,
            )
            current = session.get(User, auth.user_id)
            if current is None:
                raise TenantPhoneChangeConflict()
            old_phone = _row_phone(current)
            self._phones.ensure_candidate_available(
                session,
                current_user_uuid=UUID(auth.user_id),
                new_phone=new_phone,
            )
            context = _context(
                auth=auth,
                action_uuid=action_uuid,
                old_phone=old_phone,
                new_phone=new_phone,
            )
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).active_key
            prepared = self._intents.prepare_phone_change(
                session,
                context=context,
                old_phone=old_phone,
                new_phone=new_phone,
                trusted_source=source,
                root_key=root_key,
                sms_policy=self._delivery.policy,
                database_now=now,
            )
            if not prepared.replayed:
                session.add_all(
                    (
                        _event(
                            context=context,
                            challenge_uuid=prepared.old_challenge_uuid,
                            event_type="sensitive_challenge_requested",
                            reason_code="phone_change_old_requested",
                            safe_outcome="challenge_committed",
                            created_at=now,
                        ),
                        _event(
                            context=context,
                            challenge_uuid=prepared.new_challenge_uuid,
                            event_type="sensitive_challenge_requested",
                            reason_code="phone_change_new_requested",
                            safe_outcome="challenge_committed",
                            created_at=now,
                        ),
                    )
                )

        for delivery in prepared.deliveries:
            self._delivery.dispatch_committed(delivery)
        return {
            "intent_id": str(prepared.intent_uuid),
            "old_challenge_id": str(prepared.old_challenge_uuid),
            "new_challenge_id": str(prepared.new_challenge_uuid),
            "expires_at": _iso(prepared.expires_at),
            "replayed": prepared.replayed,
        }

    def confirm(
        self,
        *,
        flask_request: Request,
        raw_new_phone: object,
        action_id: object,
        old_challenge_id: object,
        old_plaintext_code: object,
        new_challenge_id: object,
        new_plaintext_code: object,
    ) -> dict[str, object]:
        new_phone = _phone(raw_new_phone)
        action_uuid = _uuid(action_id)
        old_challenge_uuid = _uuid(old_challenge_id)
        new_challenge_uuid = _uuid(new_challenge_id)
        rejected = False
        result = None
        with self._control_database.transaction() as session:
            now = _database_now(session)
            auth = self._tenant_http_boundary.authorize(
                session,
                flask_request,
                capability=Capability.PHONE_SELF_CHANGE,
                now=now,
            )
            current = session.get(User, auth.user_id)
            intent = session.get(TenantSensitiveActionIntent, str(action_uuid))
            if current is None or intent is None:
                raise TenantPhoneChangeConflict()
            old_phone = _row_phone(current)
            context = _context(
                auth=auth,
                action_uuid=action_uuid,
                old_phone=old_phone,
                new_phone=new_phone,
            )
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).key_for_existing_reference(intent.root_key_version)

            savepoint = session.begin_nested()
            try:
                scope = self._phones.lock_scope(
                    session,
                    tenant_uuid=UUID(auth.tenant_id),
                    current_user_uuid=UUID(auth.user_id),
                    actor_session_uuid=UUID(auth.session_id),
                    change_uuid=action_uuid,
                    expected_auth_version=auth.user_auth_version,
                    expected_tenant_access_version=auth.tenant_access_version,
                    old_phone=old_phone,
                    new_phone=new_phone,
                    old_challenge_uuid=old_challenge_uuid,
                    new_challenge_uuid=new_challenge_uuid,
                    database_now=now,
                )
                verified = self._intents.authorize_phone_change(
                    session,
                    context=context,
                    old_phone=old_phone,
                    new_phone=new_phone,
                    old_challenge_uuid=old_challenge_uuid,
                    old_plaintext_code=old_plaintext_code,
                    new_challenge_uuid=new_challenge_uuid,
                    new_plaintext_code=new_plaintext_code,
                    root_key=root_key,
                    database_now=now,
                )
                if not verified.accepted or verified.already_succeeded:
                    savepoint.rollback()
                    retried = self._intents.authorize_phone_change(
                        session,
                        context=context,
                        old_phone=old_phone,
                        new_phone=new_phone,
                        old_challenge_uuid=old_challenge_uuid,
                        old_plaintext_code=old_plaintext_code,
                        new_challenge_uuid=new_challenge_uuid,
                        new_plaintext_code=new_plaintext_code,
                        root_key=root_key,
                        database_now=now,
                    )
                    if retried.accepted:
                        raise RuntimeError("phone verification rollback failed")
                    session.add(
                        _event(
                            context=context,
                            challenge_uuid=old_challenge_uuid,
                            event_type="sensitive_challenge_rejected",
                            reason_code="phone_change_verification_rejected",
                            safe_outcome="rejected",
                            created_at=now,
                        )
                    )
                    rejected = True
                else:
                    assert verified.authorization is not None
                    result = self._phones.apply_locked(
                        session,
                        scope=scope,
                        proof=PhoneChangeAuthorizationProof(
                            tenant_uuid=UUID(auth.tenant_id),
                            user_uuid=UUID(auth.user_id),
                            actor_session_uuid=UUID(auth.session_id),
                            change_uuid=action_uuid,
                            old_challenge_uuid=old_challenge_uuid,
                            new_challenge_uuid=new_challenge_uuid,
                            expected_auth_version=auth.user_auth_version,
                            old_phone_e164=old_phone.e164,
                            new_phone_e164=new_phone.e164,
                        ),
                        new_phone=new_phone,
                        database_now=now,
                    )
                    self._intents.mark_succeeded(
                        session,
                        authorization=verified.authorization,
                        safe_result_code="phone_changed",
                        correlation_id=(
                            f"user:{result.user_uuid}:auth:{result.auth_version}:"
                            f"sessions:{result.sessions_revoked}:"
                            f"invitations:{result.invitations_superseded}"
                        ),
                        database_now=now,
                    )
                    session.add_all(
                        (
                            _event(
                                context=context,
                                challenge_uuid=old_challenge_uuid,
                                event_type="sensitive_challenge_verified",
                                reason_code="phone_change_old_verified",
                                safe_outcome="verified",
                                created_at=now,
                            ),
                            _event(
                                context=context,
                                challenge_uuid=new_challenge_uuid,
                                event_type="sensitive_challenge_verified",
                                reason_code="phone_change_new_verified",
                                safe_outcome="verified",
                                created_at=now,
                            ),
                            _event(
                                context=context,
                                challenge_uuid=old_challenge_uuid,
                                event_type="sensitive_action_committed",
                                reason_code="phone_change_committed",
                                safe_outcome="succeeded",
                                created_at=now,
                            ),
                        )
                    )
                    savepoint.commit()
            except Exception:
                if savepoint.is_active:
                    savepoint.rollback()
                raise
        if rejected:
            raise TenantPhoneChangeVerificationRejected()
        if result is None:
            raise RuntimeError("phone change result is unavailable")
        return {
            "phone_changed": True,
            "user_id": str(result.user_uuid),
            "auth_version": result.auth_version,
            "sessions_revoked": result.sessions_revoked,
            "invitations_superseded": result.invitations_superseded,
            "login_required": True,
        }


def translate_phone_change_error(exc: Exception) -> TenantHttpError | RuntimeError:
    if isinstance(exc, TenantHttpError):
        return exc
    if isinstance(exc, SmsSendRejected):
        from .http_runtime import TenantSmsRateLimited

        return TenantSmsRateLimited(
            retry_after_seconds=exc.retry_after_seconds
        )
    if isinstance(
        exc,
        (PhoneChangeConflictError, SensitiveActionConflictError),
    ):
        return TenantPhoneChangeConflict()
    if isinstance(
        exc,
        (PhoneChangeInputError, SensitiveActionInputError, TypeError, ValueError),
    ):
        return TenantPhoneChangeInputRejected()
    return exc


def _context(
    *,
    auth,
    action_uuid: UUID,
    old_phone: CanonicalSmsPhone,
    new_phone: CanonicalSmsPhone,
) -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=action_uuid,
        tenant_uuid=UUID(auth.tenant_id),
        actor_user_uuid=UUID(auth.user_id),
        actor_session_uuid=UUID(auth.session_id),
        purpose=SmsPurpose.PHONE_CHANGE_OLD,
        action_subtype="identity.phone_change",
        target_type="tenant_user",
        target_uuid=UUID(auth.user_id),
        expected_target_revision=f"auth:{auth.user_auth_version}",
        action_payload=CanonicalActionPayload.from_value(
            {
                "new_phone_e164": new_phone.e164,
                "old_phone_e164": old_phone.e164,
            }
        ),
        idempotency_key=f"phone-change:{action_uuid}",
    )


def _event(**kwargs):
    return build_sensitive_action_security_event(**kwargs)


def _phone(value: object) -> CanonicalSmsPhone:
    if not isinstance(value, str):
        raise TenantPhoneChangeInputRejected()
    try:
        return CanonicalSmsPhone.from_input(value)
    except (TypeError, ValueError):
        raise TenantPhoneChangeInputRejected() from None


def _row_phone(row: User) -> CanonicalSmsPhone:
    try:
        return CanonicalSmsPhone(
            e164=row.phone_e164,
            normalization_version=row.phone_normalization_version,
            metadata_version=row.phone_metadata_version,
        )
    except (TypeError, ValueError):
        raise TenantPhoneChangeConflict() from None


def _uuid(value: object) -> UUID:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise TenantPhoneChangeInputRejected() from None
    if str(parsed) != str(value).lower():
        raise TenantPhoneChangeInputRejected()
    return parsed


def _database_now(session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database time is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "TenantPhoneChangeConflict",
    "TenantPhoneChangeInputRejected",
    "TenantPhoneChangeRuntime",
    "TenantPhoneChangeVerificationRejected",
    "translate_phone_change_error",
]
