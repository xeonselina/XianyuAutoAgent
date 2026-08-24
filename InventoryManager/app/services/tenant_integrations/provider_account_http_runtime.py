"""D48 HTTP runtime for SF provider-account bind submissions."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Mapping, Protocol
from uuid import UUID

from flask import current_app
import sqlalchemy as sa

from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from app.services.tenant_identity.sensitive_events import (
    build_sensitive_action_security_event,
)
from app.services.tenant_identity.sms_runtime import TenantSmsDeliveryRuntime
from app.services.warehouse import (
    WarehouseProviderBindingConflictError,
    WarehouseProviderBindingPlan,
    WarehouseProviderBindingService,
    WarehouseProviderBindingUnavailableError,
    WarehouseProviderUnbindingPlan,
)
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKeyLoadError, SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.integrations import (
    ProviderAccountIdempotencyConflictError,
    ProviderAccountCredentialInputError,
    ProviderAccountInputError,
    ProviderAccountPersistenceError,
    ProviderAccountStateConflictError,
    SfAdminClaimProof,
    SfClaimError,
    TenantProviderAccountBindingCoordinator,
    TenantProviderAccountQueryService,
    TenantProviderAccountService,
    canonicalize_sf_account_secret,
)
from inventory_control.jobs import ControlJobService
from inventory_control.models import (
    ProviderAccountClaimEvent,
    TenantIntegration,
    TenantIntegrationSecretRevision,
    ProviderAccountClaim,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
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

from .provider_account_validation import (
    PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE,
    PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE,
)
from .provider_binding_worker import (
    PROVIDER_BINDING_REMOVE_EVENT_TYPE,
    PROVIDER_CLAIM_RELEASE_SOURCE_TYPE,
)


TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION = (
    "tenant_provider_account_http_runtime"
)


class TenantProviderAccountRuntimeUnavailable(RuntimeError):
    pass


class TenantProviderAccountInputRejected(TenantHttpError):
    status_code = 400
    code = "SF_ACCOUNT_INPUT_INVALID"
    public_message = "顺丰月结账号请求格式无效。"


class TenantProviderAccountConflictRejected(TenantHttpError):
    status_code = 409
    code = "SF_ACCOUNT_UNAVAILABLE"
    public_message = "账号当前无法绑定，请确认原绑定仓已由 Admin 解绑并重新验证。"


class TenantProviderAccountVerificationRejected(TenantHttpError):
    status_code = 403
    code = "SF_ACCOUNT_VERIFICATION_REJECTED"
    public_message = "敏感操作验证码无效或已失效。"


class TenantProviderAccountSmsRateLimited(TenantHttpError):
    status_code = 429
    code = "SF_ACCOUNT_SMS_RATE_LIMITED"
    public_message = "验证码请求过于频繁，请稍后再试。"

    def __init__(self, *, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, min(int(retry_after_seconds), 86_400))
        super().__init__()


class TenantProviderAccountHttpRuntime(Protocol):
    def list_accounts(self, *, flask_request): ...

    def request_bind_challenge(self, *, flask_request, payload): ...

    def confirm_bind(self, *, flask_request, payload): ...

    def request_unbind_challenge(self, *, flask_request, payload): ...

    def confirm_unbind(self, *, flask_request, payload): ...


class _VerificationRejected(RuntimeError):
    pass


class SqlAlchemyTenantProviderAccountHttpRuntime:
    """Authorize locally, persist only encrypted control facts, never call SF."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        tenant_business_runtime: TenantBusinessHttpRuntime,
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
        if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
            raise TypeError("tenant_business_runtime is invalid")
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be absolute")
        if trusted_source_resolver is not None and not callable(
            trusted_source_resolver
        ):
            raise TypeError("trusted_source_resolver must be callable")
        sms = SmsChallengeService()
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._tenant_business_runtime = tenant_business_runtime
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

    @property
    def tenant_business_runtime(self) -> TenantBusinessHttpRuntime:
        return self._tenant_business_runtime

    def list_accounts(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                request_id_prefix="sf-account-list",
            ) as scope:
                local_auth = scope.auth_context
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                _same_auth(local_auth, auth)
                accounts = TenantProviderAccountQueryService(
                    session
                ).list_sf_accounts(tenant_uuid=auth.tenant_id)
            return {"items": [_settings_dto(item) for item in accounts]}
        except TenantHttpError:
            raise
        except (ProviderAccountStateConflictError, ValueError):
            raise TenantProviderAccountConflictRejected() from None
        except TenantBusinessRuntimeUnavailable:
            raise TenantProviderAccountRuntimeUnavailable() from None

    def request_bind_challenge(self, *, flask_request, payload):
        try:
            source = self._trusted_source(flask_request)
            parsed, local_auth, plan = self._local_plan(
                flask_request=flask_request,
                payload=payload,
                request_id_prefix="sf-account-bind-challenge",
            )
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                _same_auth(local_auth, auth)
                integration = _integration(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_uuid=parsed["integration_uuid"],
                )
                account = _account_snapshot(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_id=integration.id,
                    account_uuid=parsed["account_uuid"],
                )
                secret = canonicalize_sf_account_secret(parsed["account_secret"])
                account_facts = _account_context_facts(
                    session,
                    account=account,
                    action_uuid=parsed["action_uuid"],
                    account_uuid=parsed["account_uuid"],
                    tenant_id=auth.tenant_id,
                )
                context = _context(
                    auth=auth,
                    integration=integration,
                    account_facts=account_facts,
                    plan=plan,
                    parsed=parsed,
                    secret_digest=secret.canonical_semantics_digest,
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
                    session.add(_event(
                        context=context,
                        challenge_uuid=prepared.challenge_uuid,
                        event_type="sensitive_challenge_requested",
                        reason_code="sf_account_binding_requested",
                        safe_outcome="challenge_committed",
                        created_at=now,
                    ))
            if prepared.delivery is not None:
                self._delivery.dispatch_committed(prepared.delivery)
            return {
                "intent_id": str(prepared.intent_uuid),
                "challenge_id": str(prepared.challenge_uuid),
                "expires_at": prepared.expires_at.isoformat(),
                "target_binding_revision": plan.target_binding_revision,
                "replayed": prepared.replayed,
            }
        except TenantHttpError:
            raise
        except SmsSendRejected as exc:
            raise TenantProviderAccountSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except (
            ProviderAccountInputError,
            ProviderAccountCredentialInputError,
            SensitiveActionInputError,
            WarehouseProviderBindingUnavailableError,
            TypeError,
            ValueError,
        ):
            raise TenantProviderAccountInputRejected() from None
        except (
            SensitiveActionConflictError,
            WarehouseProviderBindingConflictError,
        ):
            raise TenantProviderAccountConflictRejected() from None
        except (
            ProviderAccountPersistenceError,
            RootKeyLoadError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise TenantProviderAccountRuntimeUnavailable() from None

    def confirm_bind(self, *, flask_request, payload):
        rejected = False
        submission = None
        outbox = None
        try:
            parsed, local_auth, plan = self._local_plan(
                flask_request=flask_request,
                payload=payload,
                request_id_prefix="sf-account-bind-confirm",
            )
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                _same_auth(local_auth, auth)
                integration = _integration(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_uuid=parsed["integration_uuid"],
                    for_update=True,
                )
                account = _account_snapshot(
                    session,
                    tenant_id=auth.tenant_id,
                    integration_id=integration.id,
                    account_uuid=parsed["account_uuid"],
                    for_update=True,
                )
                secret = canonicalize_sf_account_secret(parsed["account_secret"])
                account_facts = _account_context_facts(
                    session,
                    account=account,
                    action_uuid=parsed["action_uuid"],
                    account_uuid=parsed["account_uuid"],
                    tenant_id=auth.tenant_id,
                )
                context = _context(
                    auth=auth,
                    integration=integration,
                    account_facts=account_facts,
                    plan=plan,
                    parsed=parsed,
                    secret_digest=secret.canonical_semantics_digest,
                )
                challenge_uuid = parsed["challenge_uuid"]
                actor_phone = _actor_phone(session, auth.user_id)
                intent = session.get(
                    TenantSensitiveActionIntent,
                    str(context.intent_uuid),
                )
                if intent is None:
                    raise TenantProviderAccountVerificationRejected()
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                root_key = key_ring.key_for_existing_reference(
                    intent.root_key_version
                )
                if root_key.version != key_ring.active_key.version:
                    raise TenantProviderAccountConflictRejected()
                savepoint = session.begin_nested()
                try:
                    verified = self._intents.authorize_primary(
                        session,
                        context=context,
                        actor_phone=actor_phone,
                        challenge_uuid=challenge_uuid,
                        plaintext_code=parsed["code"],
                        root_key=root_key,
                        database_now=now,
                    )
                    if not verified.accepted:
                        raise _VerificationRejected()
                    proof = SfAdminClaimProof(
                        tenant_uuid=UUID(auth.tenant_id),
                        actor_user_uuid=UUID(auth.user_id),
                        actor_session_uuid=UUID(auth.session_id),
                        role=auth.role,
                        effective_gate=auth.effective_gate,
                        tenant_access_version=auth.tenant_access_version,
                        otp_challenge_uuid=challenge_uuid,
                        otp_purpose=context.purpose.value,
                        otp_action_uuid=context.intent_uuid,
                        otp_request_digest=context.action_payload.digest_sha256,
                        otp_consumed=True,
                    )
                    submission = TenantProviderAccountBindingCoordinator(
                        session
                    ).submit(
                        provider_account_uuid=parsed["account_uuid"],
                        tenant_uuid=auth.tenant_id,
                        integration_uuid=integration.id,
                        warehouse_uuid=plan.warehouse_uuid,
                        label=parsed["label"],
                        account_secret=parsed["account_secret"],
                        root_key=root_key,
                        proof=proof,
                        action_uuid=context.intent_uuid,
                        request_digest=context.action_payload.digest_sha256,
                        idempotency_key=context.idempotency_key,
                        reservation_expires_at=now + timedelta(minutes=15),
                        expected_account_row_version=(
                            None if account is None else account.row_version
                        ),
                        expected_current_secret_revision_uuid=(
                            None
                            if account is None
                            else account.current_secret_revision_id
                        ),
                        expected_current_global_claim_uuid=(
                            None
                            if account is None
                            else account.current_global_claim_id
                        ),
                        target_binding_revision=plan.target_binding_revision,
                        expected_warehouse_provider_account_uuid=(
                            plan.expected_provider_account_uuid
                        ),
                        expected_warehouse_binding_revision=(
                            plan.expected_binding_revision
                        ),
                    )
                    if not verified.already_succeeded:
                        if verified.authorization is None:
                            raise RuntimeError("sensitive authorization is missing")
                        self._intents.mark_succeeded(
                            session,
                            authorization=verified.authorization,
                            safe_result_code="provider_account_revision_pending",
                            correlation_id=(
                                f"provider-account:{parsed['account_uuid']}:"
                                f"revision:{submission.revision.revision_uuid}"
                            ),
                            database_now=now,
                        )
                        session.add_all((
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_challenge_verified",
                                reason_code="sf_account_binding_verified",
                                safe_outcome="verified",
                                created_at=now,
                            ),
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_action_committed",
                                reason_code="provider_account_revision_pending",
                                safe_outcome="succeeded",
                                created_at=now,
                            ),
                        ))
                    outbox = self._jobs.enqueue_outbox(
                        session,
                        source_type=PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE,
                        source_uuid=submission.revision.revision_uuid,
                        source_generation=submission.revision.revision_no,
                        event_type=PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE,
                        payload={
                            "revision_uuid": submission.revision.revision_uuid,
                            "revision_row_version": 1,
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
                        plaintext_code=parsed["code"],
                        root_key=root_key,
                        database_now=now,
                    )
                    if retried.accepted:
                        raise RuntimeError("sensitive verification rollback failed")
                    session.add(_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_challenge_rejected",
                        reason_code="sf_account_binding_verification_rejected",
                        safe_outcome="rejected",
                        created_at=now,
                    ))
                    rejected = True
                except Exception:
                    if savepoint.is_active:
                        savepoint.rollback()
                    raise
            if rejected:
                raise TenantProviderAccountVerificationRejected()
            if submission is None or outbox is None:
                raise TenantProviderAccountRuntimeUnavailable()
            revision = submission.revision
            return {
                "provider_account_id": revision.provider_account_uuid,
                "revision_id": revision.revision_uuid,
                "revision_no": revision.revision_no,
                "status": revision.status,
                "verification_status": revision.verification_status,
                "target_binding_revision": revision.target_binding_revision,
                "validation_event_id": str(outbox.id),
                "idempotent": submission.idempotent_replay,
            }
        except TenantHttpError:
            raise
        except (
            ProviderAccountInputError,
            ProviderAccountCredentialInputError,
            SensitiveActionInputError,
            WarehouseProviderBindingUnavailableError,
            TypeError,
            ValueError,
        ):
            raise TenantProviderAccountInputRejected() from None
        except (
            ProviderAccountIdempotencyConflictError,
            ProviderAccountStateConflictError,
            SensitiveActionConflictError,
            SfClaimError,
            WarehouseProviderBindingConflictError,
        ):
            raise TenantProviderAccountConflictRejected() from None
        except (
            ProviderAccountPersistenceError,
            RootKeyLoadError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise TenantProviderAccountRuntimeUnavailable() from None

    def request_unbind_challenge(self, *, flask_request, payload):
        try:
            source = self._trusted_source(flask_request)
            parsed, local_auth, plan = self._local_unbind_plan(
                flask_request=flask_request,
                payload=payload,
                request_id_prefix="sf-account-unbind-challenge",
            )
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                _same_auth(local_auth, auth)
                facts = _unbind_control_facts(
                    session,
                    tenant_id=auth.tenant_id,
                    account_uuid=parsed["account_uuid"],
                    warehouse_uuid=plan.warehouse_uuid,
                    action_uuid=parsed["action_uuid"],
                    expected_binding_revision=plan.expected_binding_revision,
                )
                context = _unbind_context(
                    auth=auth,
                    parsed=parsed,
                    plan=plan,
                    facts=facts,
                )
                _verify_unbind_replay_digest(facts, context=context)
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
                    session.add(_event(
                        context=context,
                        challenge_uuid=prepared.challenge_uuid,
                        event_type="sensitive_challenge_requested",
                        reason_code="sf_account_unbinding_requested",
                        safe_outcome="challenge_committed",
                        created_at=now,
                    ))
            if prepared.delivery is not None:
                self._delivery.dispatch_committed(prepared.delivery)
            return {
                "intent_id": str(prepared.intent_uuid),
                "challenge_id": str(prepared.challenge_uuid),
                "expires_at": prepared.expires_at.isoformat(),
                "expected_binding_revision": plan.expected_binding_revision,
                "replayed": prepared.replayed,
            }
        except TenantHttpError:
            raise
        except SmsSendRejected as exc:
            raise TenantProviderAccountSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except (
            ProviderAccountInputError,
            SensitiveActionInputError,
            WarehouseProviderBindingUnavailableError,
            TypeError,
            ValueError,
        ):
            raise TenantProviderAccountInputRejected() from None
        except (
            ProviderAccountStateConflictError,
            SensitiveActionConflictError,
            WarehouseProviderBindingConflictError,
        ):
            raise TenantProviderAccountConflictRejected() from None
        except (
            RootKeyLoadError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise TenantProviderAccountRuntimeUnavailable() from None

    def confirm_unbind(self, *, flask_request, payload):
        rejected = False
        released_account = None
        outbox = None
        try:
            parsed, local_auth, plan = self._local_unbind_plan(
                flask_request=flask_request,
                payload=payload,
                request_id_prefix="sf-account-unbind-confirm",
            )
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_INTEGRATIONS_MANAGE,
                    now=now,
                )
                _same_auth(local_auth, auth)
                facts = _unbind_control_facts(
                    session,
                    tenant_id=auth.tenant_id,
                    account_uuid=parsed["account_uuid"],
                    warehouse_uuid=plan.warehouse_uuid,
                    action_uuid=parsed["action_uuid"],
                    expected_binding_revision=plan.expected_binding_revision,
                )
                context = _unbind_context(
                    auth=auth,
                    parsed=parsed,
                    plan=plan,
                    facts=facts,
                )
                _verify_unbind_replay_digest(facts, context=context)
                challenge_uuid = parsed["challenge_uuid"]
                actor_phone = _actor_phone(session, auth.user_id)
                intent = session.get(
                    TenantSensitiveActionIntent,
                    str(context.intent_uuid),
                )
                if intent is None:
                    raise TenantProviderAccountVerificationRejected()
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                root_key = key_ring.key_for_existing_reference(
                    intent.root_key_version
                )
                if root_key.version != key_ring.active_key.version:
                    raise TenantProviderAccountConflictRejected()
                savepoint = session.begin_nested()
                try:
                    verified = self._intents.authorize_primary(
                        session,
                        context=context,
                        actor_phone=actor_phone,
                        challenge_uuid=challenge_uuid,
                        plaintext_code=parsed["code"],
                        root_key=root_key,
                        database_now=now,
                    )
                    if not verified.accepted:
                        raise _VerificationRejected()
                    proof = SfAdminClaimProof(
                        tenant_uuid=UUID(auth.tenant_id),
                        actor_user_uuid=UUID(auth.user_id),
                        actor_session_uuid=UUID(auth.session_id),
                        role=auth.role,
                        effective_gate=auth.effective_gate,
                        tenant_access_version=auth.tenant_access_version,
                        otp_challenge_uuid=challenge_uuid,
                        otp_purpose=SmsPurpose.SF_ACCOUNT_UNBIND.value,
                        otp_action_uuid=context.intent_uuid,
                        otp_request_digest=context.action_payload.digest_sha256,
                        otp_consumed=True,
                    )
                    released_account = TenantProviderAccountService(
                        session
                    ).release_current_claim(
                        provider_account_uuid=parsed["account_uuid"],
                        warehouse_uuid=plan.warehouse_uuid,
                        proof=proof,
                        action_uuid=context.intent_uuid,
                        request_digest=context.action_payload.digest_sha256,
                        expected_account_row_version=facts["account_row_version"],
                        expected_claim_generation=facts["claim_generation"],
                        expected_claim_row_version=facts["claim_row_version"],
                    )
                    released_claim = session.get(
                        ProviderAccountClaim,
                        facts["claim_id"],
                        populate_existing=True,
                    )
                    if (
                        released_claim is None
                        or released_claim.claim_status != "released"
                    ):
                        raise ProviderAccountStateConflictError()
                    if not verified.already_succeeded:
                        if verified.authorization is None:
                            raise RuntimeError("sensitive authorization is missing")
                        self._intents.mark_succeeded(
                            session,
                            authorization=verified.authorization,
                            safe_result_code="provider_account_claim_released",
                            correlation_id=(
                                f"provider-claim:{released_claim.id}:"
                                f"generation:{released_claim.claim_generation}"
                            ),
                            database_now=now,
                        )
                        session.add_all((
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_challenge_verified",
                                reason_code="sf_account_unbinding_verified",
                                safe_outcome="verified",
                                created_at=now,
                            ),
                            _event(
                                context=context,
                                challenge_uuid=challenge_uuid,
                                event_type="sensitive_action_committed",
                                reason_code="provider_account_claim_released",
                                safe_outcome="succeeded",
                                created_at=now,
                            ),
                        ))
                    outbox = self._jobs.enqueue_outbox(
                        session,
                        source_type=PROVIDER_CLAIM_RELEASE_SOURCE_TYPE,
                        source_uuid=released_claim.id,
                        source_generation=released_claim.claim_generation,
                        event_type=PROVIDER_BINDING_REMOVE_EVENT_TYPE,
                        payload={
                            "provider_account_uuid": str(parsed["account_uuid"]),
                            "warehouse_uuid": plan.warehouse_uuid,
                            "expected_binding_revision": (
                                plan.expected_binding_revision
                            ),
                        },
                        idempotency_key=f"sf-unbinding:{context.intent_uuid}",
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
                        plaintext_code=parsed["code"],
                        root_key=root_key,
                        database_now=now,
                    )
                    if retried.accepted:
                        raise RuntimeError("sensitive verification rollback failed")
                    session.add(_event(
                        context=context,
                        challenge_uuid=challenge_uuid,
                        event_type="sensitive_challenge_rejected",
                        reason_code="sf_account_unbinding_verification_rejected",
                        safe_outcome="rejected",
                        created_at=now,
                    ))
                    rejected = True
                except Exception:
                    if savepoint.is_active:
                        savepoint.rollback()
                    raise
            if rejected:
                raise TenantProviderAccountVerificationRejected()
            if released_account is None or outbox is None:
                raise TenantProviderAccountRuntimeUnavailable()
            return {
                "provider_account_id": released_account.provider_account_uuid,
                "status": released_account.status,
                "row_version": released_account.row_version,
                "unbinding_event_id": str(outbox.id),
                "idempotent": released_account.idempotent_replay,
            }
        except TenantHttpError:
            raise
        except (
            ProviderAccountInputError,
            SensitiveActionInputError,
            WarehouseProviderBindingUnavailableError,
            TypeError,
            ValueError,
        ):
            raise TenantProviderAccountInputRejected() from None
        except (
            ProviderAccountStateConflictError,
            SensitiveActionConflictError,
            SfClaimError,
            WarehouseProviderBindingConflictError,
        ):
            raise TenantProviderAccountConflictRejected() from None
        except (
            ProviderAccountPersistenceError,
            RootKeyLoadError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise TenantProviderAccountRuntimeUnavailable() from None

    def _local_plan(self, *, flask_request, payload, request_id_prefix):
        parsed = None

        def parse_after_authorize(_auth):
            nonlocal parsed
            parsed = _parse_payload(payload)

        with self._tenant_business_runtime.tenant_session(
            flask_request=flask_request,
            capability=Capability.TENANT_INTEGRATIONS_MANAGE,
            request_id_prefix=request_id_prefix,
            after_authorize=parse_after_authorize,
            passthrough_exceptions=(TenantProviderAccountInputRejected,),
        ) as scope:
            if parsed is None:
                raise TenantProviderAccountRuntimeUnavailable()
            with scope.tenant_session.begin():
                plan = WarehouseProviderBindingService(
                    scope.tenant_session
                ).plan_sf_account_binding(
                    warehouse_uuid=parsed["warehouse_uuid"],
                    provider_account_uuid=parsed["account_uuid"],
                )
        if (
            plan.expected_provider_account_uuid is not None
            and not plan.binding_already_current
        ):
            # Cross-fingerprint replacement must first release the old global
            # claim through its own D48/reconciliation path.
            raise TenantProviderAccountConflictRejected()
        return parsed, scope.auth_context, plan

    def _local_unbind_plan(self, *, flask_request, payload, request_id_prefix):
        parsed = None

        def parse_after_authorize(_auth):
            nonlocal parsed
            parsed = _parse_unbind_payload(payload)

        with self._tenant_business_runtime.tenant_session(
            flask_request=flask_request,
            capability=Capability.TENANT_INTEGRATIONS_MANAGE,
            request_id_prefix=request_id_prefix,
            after_authorize=parse_after_authorize,
            passthrough_exceptions=(TenantProviderAccountInputRejected,),
        ) as scope:
            if parsed is None:
                raise TenantProviderAccountRuntimeUnavailable()
            with scope.tenant_session.begin():
                plan = WarehouseProviderBindingService(
                    scope.tenant_session
                ).plan_sf_account_unbinding(
                    warehouse_uuid=parsed["warehouse_uuid"],
                    provider_account_uuid=parsed["account_uuid"],
                )
        return parsed, scope.auth_context, plan

    def _trusted_source(self, flask_request) -> TrustedSourceBucket:
        if not callable(self._trusted_source_resolver):
            raise TenantProviderAccountRuntimeUnavailable()
        source = self._trusted_source_resolver(flask_request)
        if not isinstance(source, TrustedSourceBucket):
            raise TenantProviderAccountRuntimeUnavailable()
        return source


def require_tenant_provider_account_http_runtime():
    runtime = current_app.extensions.get(
        TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION
    )
    if runtime is None:
        raise TenantProviderAccountRuntimeUnavailable()
    return runtime


def _context(
    *,
    auth,
    integration,
    account_facts,
    plan,
    parsed,
    secret_digest,
) -> SensitiveActionContext:
    purpose = (
        SmsPurpose.SF_ACCOUNT_BIND
        if plan.expected_binding_revision is None
        else SmsPurpose.SF_ACCOUNT_REBIND
    )
    action_payload = CanonicalActionPayload.from_value({
        "account_semantics_digest": secret_digest.hex(),
        "expected_account_row_version": (
            account_facts["row_version"]
        ),
        "expected_current_claim_uuid": (
            account_facts["current_claim_id"]
        ),
        "expected_current_secret_revision_uuid": (
            account_facts["current_revision_id"]
        ),
        "expected_integration_row_version": integration.row_version,
        "expected_integration_secret_revision_uuid": (
            integration.current_secret_revision_id
        ),
        "expected_warehouse_binding_revision": (
            plan.expected_binding_revision
        ),
        "expected_warehouse_provider_account_uuid": (
            plan.expected_provider_account_uuid
        ),
        "integration_uuid": integration.id,
        "label": parsed["label"],
        "provider": "sf",
        "provider_account_uuid": str(parsed["account_uuid"]),
        "target_binding_revision": plan.target_binding_revision,
        "tenant_access_version": auth.tenant_access_version,
        "tenant_uuid": auth.tenant_id,
        "warehouse_uuid": plan.warehouse_uuid,
    })
    return SensitiveActionContext(
        intent_uuid=parsed["action_uuid"],
        tenant_uuid=UUID(auth.tenant_id),
        actor_user_uuid=UUID(auth.user_id),
        actor_session_uuid=UUID(auth.session_id),
        purpose=purpose,
        action_subtype=(
            "sf.account_bind"
            if purpose is SmsPurpose.SF_ACCOUNT_BIND
            else "sf.account_rebind"
        ),
        target_type="warehouse",
        target_uuid=UUID(plan.warehouse_uuid),
        expected_target_revision=(
            f"binding:{plan.expected_binding_revision or 'absent'}:"
            f"target:{plan.target_binding_revision}"
        ),
        action_payload=action_payload,
        idempotency_key=f"sf-account:{parsed['action_uuid']}",
    )


def _parse_payload(payload) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TenantProviderAccountInputRejected()
    label = payload.get("label")
    account_secret = payload.get("account")
    if (
        not isinstance(label, str)
        or label != label.strip()
        or not 1 <= len(label) <= 120
        or any(ord(char) < 32 or ord(char) == 127 for char in label)
        or not isinstance(account_secret, str)
    ):
        raise TenantProviderAccountInputRejected()
    parsed = {
        "action_uuid": _uuid(payload.get("action_id")),
        "warehouse_uuid": _uuid(payload.get("warehouse_id")),
        "account_uuid": _uuid(payload.get("provider_account_id")),
        "integration_uuid": _uuid(payload.get("integration_id")),
        "label": label,
        "account_secret": account_secret,
    }
    if "challenge_id" in payload or "code" in payload:
        parsed["challenge_uuid"] = _uuid(payload.get("challenge_id"))
        parsed["code"] = payload.get("code")
    return parsed


def _parse_unbind_payload(payload) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TenantProviderAccountInputRejected()
    parsed = {
        "action_uuid": _uuid(payload.get("action_id")),
        "warehouse_uuid": _uuid(payload.get("warehouse_id")),
        "account_uuid": _uuid(payload.get("provider_account_id")),
    }
    if "challenge_id" in payload or "code" in payload:
        parsed["challenge_uuid"] = _uuid(payload.get("challenge_id"))
        code = payload.get("code")
        if not isinstance(code, str):
            raise TenantProviderAccountInputRejected()
        parsed["code"] = code
    return parsed


def _unbind_control_facts(
    session,
    *,
    tenant_id,
    account_uuid,
    warehouse_uuid,
    action_uuid,
    expected_binding_revision,
):
    account_id = str(account_uuid)
    warehouse_id = str(warehouse_uuid)
    action_id = str(action_uuid)
    account = session.scalar(
        sa.select(TenantProviderAccount)
        .where(
            TenantProviderAccount.id == account_id,
            TenantProviderAccount.tenant_id == tenant_id,
            TenantProviderAccount.provider == "sf",
        )
        .with_for_update()
    )
    if account is None:
        raise TenantProviderAccountConflictRejected()

    # Once the control release has committed, rebuild the exact pre-release
    # fences from its immutable event.  Only the immediately released terminal
    # state is replayable; later reservation/activation must never be undone by
    # an old browser retry.
    release_event = session.scalar(
        sa.select(ProviderAccountClaimEvent).where(
            ProviderAccountClaimEvent.source_action_uuid == action_id,
            ProviderAccountClaimEvent.to_status == "released",
            ProviderAccountClaimEvent.actor_type == "tenant_admin",
            ProviderAccountClaimEvent.previous_provider_account_id == account_id,
            ProviderAccountClaimEvent.previous_tenant_id == tenant_id,
            ProviderAccountClaimEvent.previous_warehouse_uuid == warehouse_id,
        )
    )
    if release_event is not None:
        claim = session.scalar(
            sa.select(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.id
                == release_event.provider_account_claim_id
            )
            .with_for_update()
        )
        if (
            account.status != "inactive"
            or account.current_global_claim_id is not None
            or account.current_claim_generation is not None
            or account.row_version < 2
            or claim is None
            or claim.claim_status != "released"
            or claim.claim_generation != release_event.claim_generation
            or claim.row_version < 2
            or claim.last_action_uuid != action_id
            or claim.last_request_digest != release_event.request_digest
        ):
            raise TenantProviderAccountConflictRejected()
        return {
            "account_row_version": account.row_version - 1,
            "claim_id": claim.id,
            "claim_generation": release_event.claim_generation - 1,
            "claim_row_version": claim.row_version - 1,
            "expected_binding_revision": expected_binding_revision,
            "release_event": release_event,
        }

    claim = (
        None
        if account.current_global_claim_id is None
        else session.scalar(
            sa.select(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.id == account.current_global_claim_id
            )
            .with_for_update()
        )
    )
    revision = (
        None
        if account.current_secret_revision_id is None
        else session.get(
            TenantProviderAccountSecretRevision,
            account.current_secret_revision_id,
        )
    )
    if (
        account.status != "active"
        or account.current_claim_generation is None
        or claim is None
        or claim.claim_status != "active"
        or claim.claim_generation != account.current_claim_generation
        or claim.current_provider_account_id != account.id
        or claim.current_tenant_id != tenant_id
        or claim.current_warehouse_uuid != warehouse_id
        or claim.active_binding_revision != expected_binding_revision
        or revision is None
        or revision.status != "current"
        or revision.verification_status != "succeeded"
        or revision.tenant_provider_account_id != account.id
        or revision.provider_account_claim_id != claim.id
        or revision.activated_claim_generation != claim.claim_generation
    ):
        raise TenantProviderAccountConflictRejected()
    return {
        "account_row_version": account.row_version,
        "claim_id": claim.id,
        "claim_generation": claim.claim_generation,
        "claim_row_version": claim.row_version,
        "expected_binding_revision": expected_binding_revision,
        "release_event": None,
    }


def _unbind_context(*, auth, parsed, plan, facts) -> SensitiveActionContext:
    action_payload = CanonicalActionPayload.from_value({
        "expected_account_row_version": facts["account_row_version"],
        "expected_claim_generation": facts["claim_generation"],
        "expected_claim_row_version": facts["claim_row_version"],
        "expected_warehouse_binding_revision": (
            facts["expected_binding_revision"]
        ),
        "provider": "sf",
        "provider_account_claim_uuid": facts["claim_id"],
        "provider_account_uuid": str(parsed["account_uuid"]),
        "tenant_access_version": auth.tenant_access_version,
        "tenant_uuid": auth.tenant_id,
        "warehouse_uuid": plan.warehouse_uuid,
    })
    return SensitiveActionContext(
        intent_uuid=parsed["action_uuid"],
        tenant_uuid=UUID(auth.tenant_id),
        actor_user_uuid=UUID(auth.user_id),
        actor_session_uuid=UUID(auth.session_id),
        purpose=SmsPurpose.SF_ACCOUNT_UNBIND,
        action_subtype="sf.account_unbind",
        target_type="warehouse",
        target_uuid=UUID(plan.warehouse_uuid),
        expected_target_revision=(
            f"binding:{plan.expected_binding_revision}:remove"
        ),
        action_payload=action_payload,
        idempotency_key=f"sf-unbinding:{parsed['action_uuid']}",
    )


def _verify_unbind_replay_digest(facts, *, context) -> None:
    event = facts["release_event"]
    if event is not None and (
        event.source_action_uuid != str(context.intent_uuid)
        or event.request_digest != context.action_payload.digest_sha256
    ):
        raise TenantProviderAccountConflictRejected()


def _integration(
    session,
    *,
    tenant_id: str,
    integration_uuid: UUID,
    for_update: bool = False,
):
    statement = sa.select(TenantIntegration).where(
        TenantIntegration.id == str(integration_uuid),
        TenantIntegration.tenant_id == tenant_id,
        TenantIntegration.provider == "sf",
        TenantIntegration.status == "active",
        TenantIntegration.current_secret_revision_id.is_not(None),
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise TenantProviderAccountConflictRejected()
    revision = session.get(
        TenantIntegrationSecretRevision,
        row.current_secret_revision_id,
    )
    if (
        revision is None
        or revision.tenant_integration_id != row.id
        or revision.tenant_id != tenant_id
        or revision.provider != "sf"
        or revision.status != "current"
        or revision.verification_status != "succeeded"
    ):
        raise TenantProviderAccountConflictRejected()
    return row


def _account_snapshot(
    session,
    *,
    tenant_id,
    integration_id,
    account_uuid,
    for_update=False,
):
    statement = sa.select(TenantProviderAccount).where(
        TenantProviderAccount.id == str(account_uuid)
    )
    if for_update:
        statement = statement.with_for_update()
    account = session.scalar(statement)
    if account is not None and (
        account.tenant_id != tenant_id
        or account.integration_id != integration_id
        or account.provider != "sf"
    ):
        raise TenantProviderAccountConflictRejected()
    return account


def _account_context_facts(
    session,
    *,
    account,
    action_uuid,
    account_uuid,
    tenant_id,
):
    revision = session.scalar(
        sa.select(TenantProviderAccountSecretRevision).where(
            TenantProviderAccountSecretRevision.created_from_action_uuid
            == str(action_uuid),
            TenantProviderAccountSecretRevision.request_idempotency_key
            == f"sf-account:{action_uuid}",
            TenantProviderAccountSecretRevision.tenant_provider_account_id
            == str(account_uuid),
            TenantProviderAccountSecretRevision.tenant_id == tenant_id,
        )
    )
    if revision is not None:
        return {
            "row_version": (
                None
                if revision.expected_account_absent
                else revision.expected_account_row_version
            ),
            "current_revision_id": revision.expected_current_secret_revision_id,
            "current_claim_id": revision.expected_current_global_claim_id,
        }
    return {
        "row_version": None if account is None else account.row_version,
        "current_revision_id": (
            None if account is None else account.current_secret_revision_id
        ),
        "current_claim_id": (
            None if account is None else account.current_global_claim_id
        ),
    }


def _actor_phone(session, user_id: str) -> CanonicalSmsPhone:
    user = session.get(User, user_id)
    if user is None or user.phone_verified_at is None:
        raise TenantProviderAccountRuntimeUnavailable()
    try:
        return CanonicalSmsPhone(
            e164=user.phone_e164,
            normalization_version=user.phone_normalization_version,
            metadata_version=user.phone_metadata_version,
        )
    except Exception:
        raise TenantProviderAccountRuntimeUnavailable() from None


def _same_auth(first, second) -> None:
    if (
        first.tenant_id != second.tenant_id
        or first.user_id != second.user_id
        or first.session_id != second.session_id
        or first.role is not second.role
        or first.effective_gate is not second.effective_gate
        or first.tenant_access_version != second.tenant_access_version
    ):
        raise TenantProviderAccountConflictRejected()


def _uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise TenantProviderAccountInputRejected() from None


def _database_now(session):
    return read_database_utc_value(session)


def _event(**kwargs):
    return build_sensitive_action_security_event(**kwargs)


def _settings_dto(item) -> dict[str, object]:
    return {
        "provider_account_id": item.provider_account_uuid,
        "integration_id": item.integration_uuid,
        "connection_name": item.integration_name,
        "label": item.label,
        "masked_hint": item.masked_hint,
        "status": item.status,
        "verification_status": item.verification_status,
        "warehouse_id": item.warehouse_uuid,
        "binding_revision": item.binding_revision,
        "last_verified_at": (
            None
            if item.last_verified_at is None
            else item.last_verified_at.isoformat()
        ),
        "row_version": item.row_version,
    }


__all__ = [
    "TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantProviderAccountHttpRuntime",
    "TenantProviderAccountConflictRejected",
    "TenantProviderAccountHttpRuntime",
    "TenantProviderAccountInputRejected",
    "TenantProviderAccountRuntimeUnavailable",
    "TenantProviderAccountSmsRateLimited",
    "TenantProviderAccountVerificationRejected",
    "require_tenant_provider_account_http_runtime",
]
