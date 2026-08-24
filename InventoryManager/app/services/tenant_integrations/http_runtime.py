"""Control-only tenant integration metadata and D48 credential changes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Protocol
from uuid import UUID

from flask import current_app
import sqlalchemy as sa

from app.services.tenant_identity.sensitive_events import (
    build_sensitive_action_security_event,
)
from app.services.tenant_identity.sms_runtime import TenantSmsDeliveryRuntime
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKeyLoadError, SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.integrations import (
    IntegrationIdempotencyConflictError,
    IntegrationInputError,
    IntegrationNotFoundError,
    IntegrationPersistenceError,
    IntegrationStateConflictError,
    TenantIntegrationService,
    canonicalize_provider_credentials,
)
from inventory_control.jobs import ControlJobService
from inventory_control.models import (
    TenantIntegration,
    TenantSensitiveActionIntent,
    User,
)
from inventory_control.sensitive_actions import (
    SensitiveActionConflictError,
    SensitiveActionContext,
    SensitiveActionInputError,
    SensitiveActionIntentService,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeService,
    SmsPolicy,
    SmsProvider,
    SmsPurpose,
    SmsSendRejected,
    TrustedSourceBucket,
)
from inventory_control.tenant_http import TenantHttpBoundary, TenantHttpError


TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION = "tenant_integration_http_runtime"


class TenantIntegrationRuntimeUnavailable(RuntimeError):
    """The integration control runtime is absent or not safely configured."""


class TenantIntegrationInputRejected(TenantHttpError):
    status_code = 400
    code = "TENANT_INTEGRATION_INPUT_INVALID"
    public_message = "集成设置请求格式无效。"


class TenantIntegrationConflictRejected(TenantHttpError):
    status_code = 409
    code = "TENANT_INTEGRATION_CONFLICT"
    public_message = "集成设置已变化，请刷新后重试。"


class TenantIntegrationVerificationRejected(TenantHttpError):
    status_code = 403
    code = "TENANT_INTEGRATION_VERIFICATION_REJECTED"
    public_message = "敏感操作验证码无效或已失效。"


class TenantIntegrationSmsRateLimited(TenantHttpError):
    status_code = 429
    code = "TENANT_INTEGRATION_SMS_RATE_LIMITED"
    public_message = "验证码请求过于频繁，请稍后再试。"

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, min(int(retry_after_seconds), 86_400))
        super().__init__()


class TenantIntegrationHttpRuntime(Protocol):
    def list_integrations(self, *, flask_request): ...

    def create_integration(self, *, flask_request, payload): ...

    def request_credential_challenge(
        self, *, flask_request, integration_id, payload
    ): ...

    def confirm_credential_change(
        self, *, flask_request, integration_id, payload
    ): ...


class _VerificationRejected(RuntimeError):
    pass


class SqlAlchemyTenantIntegrationHttpRuntime:
    """Keep provider credentials write-only and provider I/O outside Web."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_root_key_directory",
        "_trusted_source_resolver",
        "_delivery",
        "_intents",
        "_jobs",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        root_key_directory: str | os.PathLike[str],
        sms_provider: SmsProvider | None,
        sms_policy: SmsPolicy | None,
        trusted_source_resolver,
        job_service: ControlJobService | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be an absolute path")
        if trusted_source_resolver is not None and not callable(
            trusted_source_resolver
        ):
            raise TypeError("trusted_source_resolver must be callable")
        sms = SmsChallengeService()
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._root_key_directory = root
        self._trusted_source_resolver = trusted_source_resolver
        self._delivery = TenantSmsDeliveryRuntime(
            control_database=control_database,
            root_key_directory=root,
            provider=sms_provider,
            policy=sms_policy,
            trusted_source_resolver=trusted_source_resolver,
            challenge_service=sms,
        )
        self._intents = SensitiveActionIntentService(
            sms_challenge_service=sms
        )
        self._jobs = job_service or ControlJobService()

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    def list_integrations(self, *, flask_request):
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_READ,
                    now=now,
                )
                rows = session.scalars(
                    sa.select(TenantIntegration)
                    .where(TenantIntegration.tenant_id == auth.tenant_id)
                    .order_by(
                        TenantIntegration.provider.asc(),
                        TenantIntegration.name.asc(),
                        TenantIntegration.id.asc(),
                    )
                ).all()
                return {"items": [_safe_integration(row) for row in rows]}
        except TenantHttpError:
            raise
        except Exception:
            raise TenantIntegrationRuntimeUnavailable() from None

    def create_integration(self, *, flask_request, payload):
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                body = _payload(payload)
                result = TenantIntegrationService(session).create_integration(
                    integration_uuid=_uuid(body.get("integration_id")),
                    tenant_uuid=auth.tenant_id,
                    provider=body.get("provider"),
                    name=body.get("name"),
                    config=_mapping(body.get("config", {})),
                )
                return {
                    "integration_id": result.integration_uuid,
                    "provider": result.provider,
                    "name": result.name,
                    "status": result.status,
                    "configured": result.current_secret_revision_uuid is not None,
                    "row_version": result.row_version,
                    "idempotent": result.idempotent_replay,
                }
        except TenantHttpError:
            raise
        except (IntegrationInputError, TypeError, ValueError):
            raise TenantIntegrationInputRejected() from None
        except IntegrationIdempotencyConflictError:
            raise TenantIntegrationConflictRejected() from None
        except (IntegrationNotFoundError, IntegrationPersistenceError):
            raise TenantIntegrationRuntimeUnavailable() from None

    def request_credential_challenge(
        self,
        *,
        flask_request,
        integration_id,
        payload,
    ):
        try:
            source = self._trusted_source(flask_request)
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                body = _payload(payload)
                integration = _integration(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_uuid=_uuid(integration_id),
                )
                action_uuid = _uuid(body.get("action_id"))
                expected_row = _positive(body.get("expected_row_version"))
                expected_current = (
                    UUID(integration.current_secret_revision_id)
                    if integration.current_secret_revision_id is not None
                    else None
                )
                _require_expected(integration, expected_row, expected_current)
                credentials = _credentials(body.get("credentials"))
                bundle = canonicalize_provider_credentials(
                    integration.provider,
                    credentials,
                )
                context = _context(
                    auth=auth,
                    integration=integration,
                    action_uuid=action_uuid,
                    expected_row_version=expected_row,
                    expected_current_revision_uuid=expected_current,
                    credential_digest=bundle.canonical_semantics_digest,
                )
                actor_phone = _actor_phone(session, auth.user_id)
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
                        _event(
                            context=context,
                            challenge_uuid=prepared.challenge_uuid,
                            event_type="sensitive_challenge_requested",
                            reason_code="integration_credential_change_requested",
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
        except TenantHttpError:
            raise
        except SmsSendRejected as exc:
            raise TenantIntegrationSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except (
            IntegrationInputError,
            SensitiveActionInputError,
            TypeError,
            ValueError,
        ):
            raise TenantIntegrationInputRejected() from None
        except (
            IntegrationStateConflictError,
            SensitiveActionConflictError,
        ):
            raise TenantIntegrationConflictRejected() from None
        except (
            IntegrationNotFoundError,
            IntegrationPersistenceError,
            RootKeyLoadError,
        ):
            raise TenantIntegrationRuntimeUnavailable() from None

    def confirm_credential_change(
        self,
        *,
        flask_request,
        integration_id,
        payload,
    ):
        rejected = False
        result = None
        outbox = None
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                body = _payload(payload)
                integration = _integration(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_uuid=_uuid(integration_id),
                    for_update=True,
                )
                action_uuid = _uuid(body.get("action_id"))
                challenge_uuid = _uuid(body.get("challenge_id"))
                expected_row = _positive(body.get("expected_row_version"))
                expected_current = (
                    UUID(integration.current_secret_revision_id)
                    if integration.current_secret_revision_id is not None
                    else None
                )
                credentials = _credentials(body.get("credentials"))
                bundle = canonicalize_provider_credentials(
                    integration.provider,
                    credentials,
                )
                context = _context(
                    auth=auth,
                    integration=integration,
                    action_uuid=action_uuid,
                    expected_row_version=expected_row,
                    expected_current_revision_uuid=expected_current,
                    credential_digest=bundle.canonical_semantics_digest,
                )
                actor_phone = _actor_phone(session, auth.user_id)
                intent = session.get(
                    TenantSensitiveActionIntent,
                    str(action_uuid),
                )
                if intent is None:
                    raise TenantIntegrationVerificationRejected()
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                root_key = key_ring.key_for_existing_reference(
                    intent.root_key_version
                )
                if root_key.version != key_ring.active_key.version:
                    raise TenantIntegrationConflictRejected()

                savepoint = session.begin_nested()
                try:
                    result = TenantIntegrationService(
                        session
                    ).create_pending_revision(
                        integration_uuid=integration.id,
                        credentials=credentials,
                        root_key=root_key,
                        created_by_user_uuid=auth.user_id,
                        action_uuid=action_uuid,
                        idempotency_key=context.idempotency_key,
                        expected_integration_row_version=expected_row,
                        expected_current_secret_revision_uuid=expected_current,
                    )
                    verified = self._intents.authorize_primary(
                        session,
                        context=context,
                        actor_phone=actor_phone,
                        challenge_uuid=challenge_uuid,
                        plaintext_code=body.get("code"),
                        root_key=root_key,
                        database_now=now,
                    )
                    if not verified.accepted:
                        raise _VerificationRejected()
                    if not verified.already_succeeded:
                        if verified.authorization is None:
                            raise RuntimeError("sensitive authorization is missing")
                        self._intents.mark_succeeded(
                            session,
                            authorization=verified.authorization,
                            safe_result_code="integration_revision_pending",
                            correlation_id=(
                                f"integration:{integration.id}:"
                                f"revision:{result.revision_uuid}:"
                                f"number:{result.revision_no}"
                            ),
                            database_now=now,
                        )
                        session.add_all((
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_challenge_verified",
                                reason_code="integration_credential_verified",
                                safe_outcome="verified",
                                created_at=now,
                            ),
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_action_committed",
                                reason_code="integration_revision_pending",
                                safe_outcome="succeeded",
                                created_at=now,
                            ),
                        ))
                    outbox = self._jobs.enqueue_outbox(
                        session,
                        source_type="tenant_integration_secret_revision",
                        source_uuid=result.revision_uuid,
                        source_generation=result.revision_no,
                        event_type="tenant_integration_credential_validate",
                        payload={
                            "integration_uuid": integration.id,
                            "revision_uuid": result.revision_uuid,
                            "revision_row_version": result.row_version,
                            "provider": integration.provider,
                        },
                        idempotency_key=context.idempotency_key,
                        tenant_id=auth.tenant_id,
                        tenant_access_version=auth.tenant_access_version,
                        max_attempts=1,
                        available_at=now,
                    )
                    savepoint.commit()
                except _VerificationRejected:
                    if savepoint.is_active:
                        savepoint.rollback()
                    retried = self._intents.authorize_primary(
                        session,
                        context=context,
                        actor_phone=actor_phone,
                        challenge_uuid=challenge_uuid,
                        plaintext_code=body.get("code"),
                        root_key=root_key,
                        database_now=now,
                    )
                    if retried.accepted:
                        raise RuntimeError("sensitive verification rollback failed")
                    session.add(
                        _event(
                            context=context,
                            challenge_uuid=challenge_uuid,
                            event_type="sensitive_challenge_rejected",
                            reason_code="integration_credential_verification_rejected",
                            safe_outcome="rejected",
                            created_at=now,
                        )
                    )
                    rejected = True
                except Exception:
                    if savepoint.is_active:
                        savepoint.rollback()
                    raise
            if rejected:
                raise TenantIntegrationVerificationRejected()
            if result is None or outbox is None:
                raise TenantIntegrationRuntimeUnavailable()
            return {
                "integration_id": result.integration_uuid,
                "revision_id": result.revision_uuid,
                "revision_no": result.revision_no,
                "status": result.status,
                "verification_status": result.verification_status,
                "validation_event_id": str(outbox.id),
                "idempotent": result.idempotent_replay,
            }
        except TenantHttpError:
            raise
        except (
            IntegrationInputError,
            SensitiveActionInputError,
            TypeError,
            ValueError,
        ):
            raise TenantIntegrationInputRejected() from None
        except (
            IntegrationIdempotencyConflictError,
            IntegrationStateConflictError,
            SensitiveActionConflictError,
        ):
            raise TenantIntegrationConflictRejected() from None
        except (
            IntegrationNotFoundError,
            IntegrationPersistenceError,
            RootKeyLoadError,
        ):
            raise TenantIntegrationRuntimeUnavailable() from None

    def _trusted_source(self, flask_request) -> TrustedSourceBucket:
        if not callable(self._trusted_source_resolver):
            raise TenantIntegrationRuntimeUnavailable()
        source = self._trusted_source_resolver(flask_request)
        if not isinstance(source, TrustedSourceBucket):
            raise TenantIntegrationRuntimeUnavailable()
        return source


def require_tenant_integration_http_runtime() -> TenantIntegrationHttpRuntime:
    runtime = current_app.extensions.get(
        TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION
    )
    if runtime is None:
        raise TenantIntegrationRuntimeUnavailable()
    return runtime


def _context(
    *,
    auth,
    integration: TenantIntegration,
    action_uuid: UUID,
    expected_row_version: int,
    expected_current_revision_uuid: UUID | None,
    credential_digest: bytes,
) -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=action_uuid,
        tenant_uuid=UUID(auth.tenant_id),
        actor_user_uuid=UUID(auth.user_id),
        actor_session_uuid=UUID(auth.session_id),
        purpose=SmsPurpose.INTEGRATION_CREDENTIAL_CHANGE,
        action_subtype="integration.credential_change",
        target_type="tenant_integration",
        target_uuid=UUID(integration.id),
        expected_target_revision=(
            f"row:{expected_row_version}:current:"
            f"{expected_current_revision_uuid or 'none'}"
        ),
        action_payload=CanonicalActionPayload.from_value({
            "credential_digest": credential_digest.hex(),
            "expected_current_revision_uuid": (
                str(expected_current_revision_uuid)
                if expected_current_revision_uuid is not None
                else None
            ),
            "expected_integration_row_version": expected_row_version,
            "integration_uuid": integration.id,
            "provider": integration.provider,
            "tenant_access_version": auth.tenant_access_version,
            "tenant_uuid": auth.tenant_id,
        }),
        idempotency_key=f"integration-credential:{action_uuid}",
    )


def _integration(
    session,
    *,
    tenant_id: str,
    integration_uuid: UUID,
    for_update: bool = False,
) -> TenantIntegration:
    statement = sa.select(TenantIntegration).where(
        TenantIntegration.id == str(integration_uuid),
        TenantIntegration.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise IntegrationNotFoundError()
    return row


def _require_expected(
    integration: TenantIntegration,
    expected_row_version: int,
    expected_current_revision_uuid: UUID | None,
) -> None:
    if (
        integration.row_version != expected_row_version
        or integration.current_secret_revision_id
        != (
            str(expected_current_revision_uuid)
            if expected_current_revision_uuid is not None
            else None
        )
    ):
        raise IntegrationStateConflictError()


def _actor_phone(session, user_id: str) -> CanonicalSmsPhone:
    user = session.get(User, user_id)
    if user is None or user.phone_verified_at is None:
        raise TenantIntegrationRuntimeUnavailable()
    try:
        return CanonicalSmsPhone(
            e164=user.phone_e164,
            normalization_version=user.phone_normalization_version,
            metadata_version=user.phone_metadata_version,
        )
    except Exception:
        raise TenantIntegrationRuntimeUnavailable() from None


def _safe_integration(row: TenantIntegration) -> dict[str, object]:
    return {
        "integration_id": row.id,
        "provider": row.provider,
        "name": row.name,
        "status": row.status,
        "configured": row.current_secret_revision_id is not None,
        "last_verified_at": _iso(row.last_verified_at),
        "row_version": row.row_version,
    }


def _event(**kwargs):
    return build_sensitive_action_security_event(**kwargs)


def _database_now(session):
    return read_database_utc_value(session)


def _iso(value):
    return value.isoformat() if value is not None else None


def _payload(value) -> dict:
    if not isinstance(value, dict):
        raise TenantIntegrationInputRejected()
    return value


def _mapping(value) -> Mapping:
    if not isinstance(value, Mapping):
        raise TenantIntegrationInputRejected()
    return value


def _credentials(value) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TenantIntegrationInputRejected()
    return value


def _uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise TenantIntegrationInputRejected() from None


def _positive(value) -> int:
    if isinstance(value, bool):
        raise TenantIntegrationInputRejected()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise TenantIntegrationInputRejected() from None
    if parsed < 1 or str(parsed) != str(value):
        raise TenantIntegrationInputRejected()
    return parsed


__all__ = [
    "TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantIntegrationHttpRuntime",
    "TenantIntegrationConflictRejected",
    "TenantIntegrationHttpRuntime",
    "TenantIntegrationInputRejected",
    "TenantIntegrationRuntimeUnavailable",
    "TenantIntegrationSmsRateLimited",
    "TenantIntegrationVerificationRejected",
    "require_tenant_integration_http_runtime",
]
