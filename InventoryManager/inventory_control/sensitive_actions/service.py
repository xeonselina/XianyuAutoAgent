"""Transactional persistence for D48 action-bound challenge intents."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import SessionTransactionOrigin

from inventory_control.crypto import RootKey
from inventory_control.models import (
    TenantSensitiveActionIntent,
    TenantSensitiveActionIntentChallenge,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeContext,
    SmsChallengeService,
    SmsPolicy,
    SmsPurpose,
    TrustedSourceBucket,
)

from .contracts import (
    AuthorizedSensitiveAction,
    PreparedSensitiveAction,
    PreparedSensitivePhoneChange,
    SensitiveActionAuthorizationResult,
    SensitiveActionChallengeRole,
    SensitiveActionConflictError,
    SensitiveActionContext,
    SensitiveActionInputError,
)
from .crypto import (
    SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
    calculate_sensitive_action_context_mac,
    verify_sensitive_action_context_mac,
)


_PHONE_CHANGE_PURPOSES = frozenset(
    {SmsPurpose.PHONE_CHANGE_OLD, SmsPurpose.PHONE_CHANGE_NEW}
)


class SensitiveActionIntentService:
    """Persist and consume exact one-shot action authorization contexts.

    Actor/session/RBAC checks stay at the calling boundary. This service owns
    only the immutable intent, its fixed-role challenge links, and their
    atomic verification state. It never commits or invokes an SMS provider.
    """

    def __init__(
        self, *, sms_challenge_service: SmsChallengeService | None = None
    ) -> None:
        self._sms = sms_challenge_service or SmsChallengeService()

    def prepare_primary(
        self,
        session: Session,
        *,
        context: SensitiveActionContext,
        actor_phone: CanonicalSmsPhone,
        trusted_source: TrustedSourceBucket,
        root_key: RootKey,
        sms_policy: SmsPolicy,
        database_now: datetime,
    ) -> PreparedSensitiveAction:
        _prepare_transaction(session)
        _require_primary_context(context)
        if not isinstance(actor_phone, CanonicalSmsPhone):
            raise SensitiveActionInputError()
        now = _as_utc(database_now)
        context_mac = calculate_sensitive_action_context_mac(
            root_key=root_key,
            context=context,
        )

        existing = session.scalar(
            sa.select(TenantSensitiveActionIntent)
            .where(
                TenantSensitiveActionIntent.tenant_id
                == str(context.tenant_uuid),
                TenantSensitiveActionIntent.idempotency_key
                == context.idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            return self._replay_preparation(
                session,
                row=existing,
                context=context,
                context_mac=context_mac,
                root_key=root_key,
            )

        sms_context = _sms_context(context, actor_phone=actor_phone)
        prepared = self._sms.prepare_delivery(
            session,
            context=sms_context,
            trusted_source=trusted_source,
            root_key=root_key,
            policy=sms_policy,
            now=now,
        )
        expires_at = now + timedelta(
            seconds=sms_policy.challenge_ttl_seconds
        )
        row = _new_intent_row(
            context=context,
            context_mac=context_mac,
            root_key=root_key,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(row)
        session.add(
            TenantSensitiveActionIntentChallenge(
                intent_id=row.id,
                challenge_role=SensitiveActionChallengeRole.PRIMARY.value,
                challenge_id=prepared.challenge_id,
                created_at=now,
            )
        )
        session.flush()
        return PreparedSensitiveAction(
            intent_uuid=context.intent_uuid,
            challenge_uuid=UUID(prepared.challenge_id),
            expires_at=expires_at,
            delivery=prepared,
            replayed=False,
        )

    def authorize_primary(
        self,
        session: Session,
        *,
        context: SensitiveActionContext,
        actor_phone: CanonicalSmsPhone,
        challenge_uuid: UUID,
        plaintext_code: object,
        root_key: RootKey,
        database_now: datetime,
    ) -> SensitiveActionAuthorizationResult:
        _prepare_transaction(session)
        _require_primary_context(context)
        if not isinstance(actor_phone, CanonicalSmsPhone) or not isinstance(
            challenge_uuid, UUID
        ):
            raise SensitiveActionInputError()
        now = _as_utc(database_now)
        row, terminal = _lock_authorizable_intent(
            session,
            context=context,
            root_key=root_key,
            database_now=now,
        )
        if terminal is not None:
            return terminal
        assert row is not None
        links = _locked_challenge_links(session, intent_id=row.id)
        if len(links) != 1 or (
            links[0].challenge_role
            != SensitiveActionChallengeRole.PRIMARY.value
            or links[0].challenge_id != str(challenge_uuid)
        ):
            raise SensitiveActionConflictError()

        verified = self._sms.verify_and_consume(
            session,
            challenge_id=str(challenge_uuid),
            context=_sms_context(context, actor_phone=actor_phone),
            plaintext_code=plaintext_code,
            root_key=root_key,
            now=now,
        )
        if not verified.accepted:
            return SensitiveActionAuthorizationResult(
                accepted=False, reason_code="SENSITIVE_ACTION_REJECTED"
            )
        row.status = "authorized"
        row.authorized_at = now
        row.updated_at = now
        row.row_version += 1
        session.flush()
        return SensitiveActionAuthorizationResult(
            accepted=True,
            reason_code="SENSITIVE_ACTION_AUTHORIZED",
            authorization=AuthorizedSensitiveAction(
                context=context,
                challenge_uuid=challenge_uuid,
                intent_row_version=row.row_version,
            ),
        )

    def prepare_phone_change(
        self,
        session: Session,
        *,
        context: SensitiveActionContext,
        old_phone: CanonicalSmsPhone,
        new_phone: CanonicalSmsPhone,
        trusted_source: TrustedSourceBucket,
        root_key: RootKey,
        sms_policy: SmsPolicy,
        database_now: datetime,
    ) -> PreparedSensitivePhoneChange:
        """Create the fixed old/new challenge pair for one phone change."""

        _prepare_transaction(session)
        _require_phone_change_context(context)
        _require_distinct_phones(old_phone, new_phone)
        now = _as_utc(database_now)
        context_mac = calculate_sensitive_action_context_mac(
            root_key=root_key,
            context=context,
        )
        existing = session.scalar(
            sa.select(TenantSensitiveActionIntent)
            .where(
                TenantSensitiveActionIntent.tenant_id
                == str(context.tenant_uuid),
                TenantSensitiveActionIntent.idempotency_key
                == context.idempotency_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            return self._replay_phone_change_preparation(
                session,
                row=existing,
                context=context,
                context_mac=context_mac,
                root_key=root_key,
            )

        prepared_old = self._sms.prepare_delivery(
            session,
            context=_sms_context(
                context,
                actor_phone=old_phone,
                purpose=SmsPurpose.PHONE_CHANGE_OLD,
            ),
            trusted_source=trusted_source,
            root_key=root_key,
            policy=sms_policy,
            now=now,
        )
        prepared_new = self._sms.prepare_delivery(
            session,
            context=_sms_context(
                context,
                actor_phone=new_phone,
                purpose=SmsPurpose.PHONE_CHANGE_NEW,
            ),
            trusted_source=trusted_source,
            root_key=root_key,
            policy=sms_policy,
            now=now,
        )
        expires_at = now + timedelta(seconds=sms_policy.challenge_ttl_seconds)
        row = _new_intent_row(
            context=context,
            context_mac=context_mac,
            root_key=root_key,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(row)
        session.add_all(
            (
                TenantSensitiveActionIntentChallenge(
                    intent_id=row.id,
                    challenge_role=SensitiveActionChallengeRole.OLD_PHONE.value,
                    challenge_id=prepared_old.challenge_id,
                    created_at=now,
                ),
                TenantSensitiveActionIntentChallenge(
                    intent_id=row.id,
                    challenge_role=SensitiveActionChallengeRole.NEW_PHONE.value,
                    challenge_id=prepared_new.challenge_id,
                    created_at=now,
                ),
            )
        )
        session.flush()
        return PreparedSensitivePhoneChange(
            intent_uuid=context.intent_uuid,
            old_challenge_uuid=UUID(prepared_old.challenge_id),
            new_challenge_uuid=UUID(prepared_new.challenge_id),
            expires_at=expires_at,
            deliveries=(prepared_old, prepared_new),
            replayed=False,
        )

    def authorize_phone_change(
        self,
        session: Session,
        *,
        context: SensitiveActionContext,
        old_phone: CanonicalSmsPhone,
        new_phone: CanonicalSmsPhone,
        old_challenge_uuid: UUID,
        old_plaintext_code: object,
        new_challenge_uuid: UUID,
        new_plaintext_code: object,
        root_key: RootKey,
        database_now: datetime,
    ) -> SensitiveActionAuthorizationResult:
        """Atomically consume both fixed-role phone-change challenges."""

        _prepare_transaction(session)
        _require_phone_change_context(context)
        _require_distinct_phones(old_phone, new_phone)
        if not isinstance(old_challenge_uuid, UUID) or not isinstance(
            new_challenge_uuid, UUID
        ) or old_challenge_uuid == new_challenge_uuid:
            raise SensitiveActionInputError()
        now = _as_utc(database_now)
        row, terminal = _lock_authorizable_intent(
            session,
            context=context,
            root_key=root_key,
            database_now=now,
        )
        if terminal is not None:
            return terminal
        assert row is not None
        links = _locked_challenge_links(session, intent_id=row.id)
        expected_links = {
            SensitiveActionChallengeRole.OLD_PHONE.value: str(
                old_challenge_uuid
            ),
            SensitiveActionChallengeRole.NEW_PHONE.value: str(
                new_challenge_uuid
            ),
        }
        if {link.challenge_role: link.challenge_id for link in links} != (
            expected_links
        ):
            raise SensitiveActionConflictError()

        contexts = (
            (
                str(old_challenge_uuid),
                _sms_context(
                    context,
                    actor_phone=old_phone,
                    purpose=SmsPurpose.PHONE_CHANGE_OLD,
                ),
                old_plaintext_code,
            ),
            (
                str(new_challenge_uuid),
                _sms_context(
                    context,
                    actor_phone=new_phone,
                    purpose=SmsPurpose.PHONE_CHANGE_NEW,
                ),
                new_plaintext_code,
            ),
        )
        savepoint = session.begin_nested()
        rejected_index: int | None = None
        try:
            for index, (challenge_id, sms_context, plaintext_code) in enumerate(
                contexts
            ):
                verified = self._sms.verify_and_consume(
                    session,
                    challenge_id=challenge_id,
                    context=sms_context,
                    plaintext_code=plaintext_code,
                    root_key=root_key,
                    now=now,
                )
                if not verified.accepted:
                    rejected_index = index
                    break
            if rejected_index is None:
                savepoint.commit()
            else:
                savepoint.rollback()
        except Exception:
            savepoint.rollback()
            raise
        if rejected_index is not None:
            challenge_id, sms_context, plaintext_code = contexts[rejected_index]
            self._sms.verify_and_consume(
                session,
                challenge_id=challenge_id,
                context=sms_context,
                plaintext_code=plaintext_code,
                root_key=root_key,
                now=now,
            )
            return SensitiveActionAuthorizationResult(
                accepted=False,
                reason_code="SENSITIVE_ACTION_REJECTED",
            )

        row.status = "authorized"
        row.authorized_at = now
        row.updated_at = now
        row.row_version += 1
        session.flush()
        return SensitiveActionAuthorizationResult(
            accepted=True,
            reason_code="SENSITIVE_ACTION_AUTHORIZED",
            authorization=AuthorizedSensitiveAction(
                context=context,
                challenge_uuid=old_challenge_uuid,
                intent_row_version=row.row_version,
            ),
        )

    def mark_succeeded(
        self,
        session: Session,
        *,
        authorization: AuthorizedSensitiveAction,
        safe_result_code: str,
        correlation_id: str | None = None,
        database_now: datetime,
    ) -> None:
        _prepare_transaction(session)
        if not isinstance(authorization, AuthorizedSensitiveAction):
            raise SensitiveActionInputError()
        if (
            not isinstance(safe_result_code, str)
            or not 1 <= len(safe_result_code) <= 64
            or not safe_result_code.isascii()
        ):
            raise SensitiveActionInputError()
        if correlation_id is not None and (
            not isinstance(correlation_id, str)
            or not 1 <= len(correlation_id) <= 128
            or not correlation_id.isascii()
        ):
            raise SensitiveActionInputError()
        now = _as_utc(database_now)
        row = session.get(
            TenantSensitiveActionIntent,
            str(authorization.context.intent_uuid),
            populate_existing=True,
        )
        if (
            row is None
            or row.status != "authorized"
            or row.row_version != authorization.intent_row_version
        ):
            raise SensitiveActionConflictError()
        row.status = "succeeded"
        row.safe_result_code = safe_result_code
        row.correlation_id = correlation_id
        row.completed_at = now
        row.updated_at = now
        row.row_version += 1
        session.flush()

    def _replay_preparation(
        self,
        session: Session,
        *,
        row: TenantSensitiveActionIntent,
        context: SensitiveActionContext,
        context_mac: bytes,
        root_key: RootKey,
    ) -> PreparedSensitiveAction:
        if not _matches_context(
            row,
            context=context,
            root_key=root_key,
            expected_mac=context_mac,
        ):
            raise SensitiveActionConflictError()
        links = _locked_challenge_links(session, intent_id=row.id)
        if len(links) != 1 or (
            links[0].challenge_role
            != SensitiveActionChallengeRole.PRIMARY.value
        ):
            raise SensitiveActionConflictError()
        return PreparedSensitiveAction(
            intent_uuid=UUID(row.id),
            challenge_uuid=UUID(links[0].challenge_id),
            expires_at=_as_utc(row.expires_at),
            delivery=None,
            replayed=True,
        )

    def _replay_phone_change_preparation(
        self,
        session: Session,
        *,
        row: TenantSensitiveActionIntent,
        context: SensitiveActionContext,
        context_mac: bytes,
        root_key: RootKey,
    ) -> PreparedSensitivePhoneChange:
        if not _matches_context(
            row,
            context=context,
            root_key=root_key,
            expected_mac=context_mac,
        ):
            raise SensitiveActionConflictError()
        links = _locked_challenge_links(session, intent_id=row.id)
        by_role = {link.challenge_role: link.challenge_id for link in links}
        if set(by_role) != {
            SensitiveActionChallengeRole.OLD_PHONE.value,
            SensitiveActionChallengeRole.NEW_PHONE.value,
        }:
            raise SensitiveActionConflictError()
        return PreparedSensitivePhoneChange(
            intent_uuid=UUID(row.id),
            old_challenge_uuid=UUID(
                by_role[SensitiveActionChallengeRole.OLD_PHONE.value]
            ),
            new_challenge_uuid=UUID(
                by_role[SensitiveActionChallengeRole.NEW_PHONE.value]
            ),
            expires_at=_as_utc(row.expires_at),
            deliveries=(),
            replayed=True,
        )


def _new_intent_row(
    *,
    context: SensitiveActionContext,
    context_mac: bytes,
    root_key: RootKey,
    created_at: datetime,
    expires_at: datetime,
) -> TenantSensitiveActionIntent:
    return TenantSensitiveActionIntent(
        id=str(context.intent_uuid),
        tenant_id=str(context.tenant_uuid),
        actor_user_id=str(context.actor_user_uuid),
        actor_session_id=str(context.actor_session_uuid),
        purpose=context.purpose.value,
        action_subtype=context.action_subtype,
        target_type=context.target_type,
        target_uuid=str(context.target_uuid),
        expected_target_revision=context.expected_target_revision,
        canonicalization_version=context.canonicalization_version,
        context_mac_version=SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
        root_key_version=root_key.version,
        request_context_mac_sha256=context_mac,
        idempotency_key=context.idempotency_key,
        status="pending_verification",
        request_id=f"sensitive-action:{context.intent_uuid}",
        row_version=1,
        created_at=created_at,
        updated_at=created_at,
        expires_at=expires_at,
    )


def _lock_authorizable_intent(
    session: Session,
    *,
    context: SensitiveActionContext,
    root_key: RootKey,
    database_now: datetime,
) -> tuple[
    TenantSensitiveActionIntent | None,
    SensitiveActionAuthorizationResult | None,
]:
    row = session.scalar(
        sa.select(TenantSensitiveActionIntent)
        .where(TenantSensitiveActionIntent.id == str(context.intent_uuid))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or not _matches_context(
        row, context=context, root_key=root_key
    ):
        raise SensitiveActionConflictError()
    if row.status == "succeeded":
        return None, SensitiveActionAuthorizationResult(
            accepted=True,
            reason_code="SENSITIVE_ACTION_ALREADY_SUCCEEDED",
            already_succeeded=True,
        )
    if row.status != "pending_verification":
        raise SensitiveActionConflictError()
    if database_now >= _as_utc(row.expires_at):
        row.status = "expired"
        row.safe_result_code = "verification_expired"
        row.completed_at = database_now
        row.updated_at = database_now
        row.row_version += 1
        session.flush()
        return None, SensitiveActionAuthorizationResult(
            accepted=False,
            reason_code="SENSITIVE_ACTION_REJECTED",
        )
    return row, None


def _locked_challenge_links(
    session: Session, *, intent_id: str
) -> tuple[TenantSensitiveActionIntentChallenge, ...]:
    return tuple(
        session.scalars(
            sa.select(TenantSensitiveActionIntentChallenge)
            .where(TenantSensitiveActionIntentChallenge.intent_id == intent_id)
            .order_by(TenantSensitiveActionIntentChallenge.challenge_role)
            .with_for_update()
        )
    )


def _matches_context(
    row: TenantSensitiveActionIntent,
    *,
    context: SensitiveActionContext,
    root_key: RootKey,
    expected_mac: bytes | None = None,
) -> bool:
    stored_mac = bytes(row.request_context_mac_sha256)
    candidate = (
        expected_mac
        if expected_mac is not None
        else calculate_sensitive_action_context_mac(
            root_key=root_key,
            context=context,
        )
    )
    return bool(
        row.id == str(context.intent_uuid)
        and row.tenant_id == str(context.tenant_uuid)
        and row.actor_user_id == str(context.actor_user_uuid)
        and row.actor_session_id == str(context.actor_session_uuid)
        and row.purpose == context.purpose.value
        and row.action_subtype == context.action_subtype
        and row.target_type == context.target_type
        and row.target_uuid == str(context.target_uuid)
        and row.expected_target_revision == context.expected_target_revision
        and row.canonicalization_version == context.canonicalization_version
        and row.context_mac_version == SENSITIVE_ACTION_CONTEXT_MAC_VERSION
        and row.root_key_version == root_key.version
        and row.idempotency_key == context.idempotency_key
        and hmac.compare_digest(stored_mac, candidate)
        and verify_sensitive_action_context_mac(
            root_key=root_key,
            context=context,
            expected_mac=stored_mac,
            mac_version=row.context_mac_version,
        )
    )


def _sms_context(
    context: SensitiveActionContext,
    *,
    actor_phone: CanonicalSmsPhone,
    purpose: SmsPurpose | None = None,
) -> SmsChallengeContext:
    return SmsChallengeContext(
        purpose=context.purpose if purpose is None else purpose,
        phone=actor_phone,
        action_payload=context.action_payload,
        authoritative_revision=f"sensitive-intent:{context.intent_uuid}:1",
        user_id=str(context.actor_user_uuid),
        tenant_id=str(context.tenant_uuid),
        actor_session_id=str(context.actor_session_uuid),
    )


def _require_primary_context(context: object) -> None:
    if not isinstance(context, SensitiveActionContext):
        raise SensitiveActionInputError()
    if context.purpose in _PHONE_CHANGE_PURPOSES:
        raise SensitiveActionInputError()


def _require_phone_change_context(context: object) -> None:
    if (
        not isinstance(context, SensitiveActionContext)
        or context.purpose is not SmsPurpose.PHONE_CHANGE_OLD
    ):
        raise SensitiveActionInputError()


def _require_distinct_phones(
    old_phone: object, new_phone: object
) -> None:
    if (
        not isinstance(old_phone, CanonicalSmsPhone)
        or not isinstance(new_phone, CanonicalSmsPhone)
        or old_phone.e164 == new_phone.e164
    ):
        raise SensitiveActionInputError()


def _prepare_transaction(session: Session) -> None:
    if not isinstance(session, Session):
        raise SensitiveActionInputError()
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        or session.new
        or session.deleted
        or any(
            session.is_modified(row, include_collections=True)
            for row in session.dirty
        )
    ):
        raise SensitiveActionInputError()


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SensitiveActionInputError()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["SensitiveActionIntentService"]
