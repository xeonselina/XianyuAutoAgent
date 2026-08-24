"""Tenant invitation HTTP application boundary and public handoff flow."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

from flask import Request, current_app
import sqlalchemy as sa

from app.services.tenant_identity.sms_runtime import TenantSmsDeliveryRuntime
from inventory_control.database import ControlDatabase
from inventory_control.domain import Capability
from inventory_control.domain import TenantRole
from inventory_control.identity import (
    LastActiveAdminError,
    MemberSeatLimitError,
    MembershipMutationAction,
    MembershipMutationAuthorityError,
    MembershipMutationConflictError,
    MembershipMutationInputError,
    TenantMembershipService,
)
from inventory_control.invitations import (
    InvitationChallengeRejectedError,
    InvitationChallengeSubmission,
    InvitationPersistenceError,
    InvitationPersistenceService,
    InvitationRole,
    issue_invitation_token,
)
from inventory_control.models import TenantInvitation
from inventory_control.sms import (
    SmsChallengeService,
    SmsPolicy,
    SmsProvider,
    SmsSendRejected,
)
from inventory_control.sensitive_actions import (
    SensitiveActionConflictError,
    SensitiveActionInputError,
    SensitiveActionIntentService,
)
from inventory_control.tenant_http import TenantHttpBoundary, TenantHttpError

from .admin_sensitive_runtime import AdminInvitationSensitiveRuntime
from .contracts import (
    TENANT_INVITATION_HTTP_RUNTIME_EXTENSION,
    TenantInvitationConflictRejected,
    TenantInvitationCredentialRejected,
    TenantInvitationHttpRuntime,
    TenantInvitationInputRejected,
    TenantInvitationRuntimeUnavailable,
    TenantInvitationSeatLimitRejected,
    TenantInvitationSmsRateLimited,
    TenantLastAdminRejected,
    TenantMemberMutationConflict,
    TenantMemberMutationVerificationRequired,
    TenantMemberMutationVerificationRejected,
)
from .member_sensitive_runtime import MemberSensitiveMutationRuntime
from .query_service import (
    InvitationQueryRejected,
    TenantInvitationQueryService,
)
from .support import (
    InvitationJoinGate as _InvitationJoinGate,
    acceptance_context as _accept_context,
    challenge_receipt as _receipt,
    challenge_root_key as _challenge_root_key,
    database_now as _database_now,
    invitation_path as _invitation_path,
    iso as _iso,
    membership_uuid as _membership_uuid,
    optional_positive as _optional_positive,
    parse_phone as _phone,
    parse_role as _role,
    parse_uuid as _uuid,
    positive as _positive,
    public_credential as _public_credential,
    translate_persistence as _translate_persistence,
)


class SqlAlchemyTenantInvitationHttpRuntime:
    """Compose RBAC, D48, SMS, and invitation state in the control DB only."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_root_key_directory",
        "_query",
        "_sms",
        "_delivery",
        "_persistence",
        "_memberships",
        "_sensitive_admin",
        "_sensitive_members",
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
        join_gate_current_read=None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be an absolute path")
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._root_key_directory = root
        self._query = TenantInvitationQueryService()
        self._sms = SmsChallengeService()
        self._delivery = TenantSmsDeliveryRuntime(
            control_database=control_database,
            root_key_directory=root,
            provider=sms_provider,
            policy=sms_policy,
            trusted_source_resolver=trusted_source_resolver,
            challenge_service=self._sms,
        )
        self._persistence = InvitationPersistenceService(
            join_gate_current_read=(
                join_gate_current_read or _InvitationJoinGate()
            ),
            sms_challenge_service=self._sms,
        )
        self._memberships = TenantMembershipService()
        intent_service = SensitiveActionIntentService(
            sms_challenge_service=self._sms
        )
        self._sensitive_admin = AdminInvitationSensitiveRuntime(
            control_database=control_database,
            tenant_http_boundary=tenant_http_boundary,
            root_key_directory=root,
            trusted_source_resolver=trusted_source_resolver,
            delivery=self._delivery,
            intent_service=intent_service,
            invitation_service=self._persistence,
        )
        self._sensitive_members = MemberSensitiveMutationRuntime(
            control_database=control_database,
            tenant_http_boundary=tenant_http_boundary,
            root_key_directory=root,
            trusted_source_resolver=trusted_source_resolver,
            delivery=self._delivery,
            intent_service=intent_service,
            membership_service=self._memberships,
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    def list_members(self, *, flask_request):
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_MEMBERS_READ,
                    now=now,
                )
                return self._query.list_for_tenant(
                    session,
                    tenant_id=auth.tenant_id,
                    database_now=now,
                )
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def mutate_member(
        self,
        *,
        flask_request,
        membership_id,
        expected_row_version,
        action,
        action_id,
        target_role=None,
    ):
        try:
            selected_action = MembershipMutationAction(action)
            selected_role = (
                None if target_role is None else TenantRole(target_role)
            )
        except (TypeError, ValueError):
            raise TenantInvitationInputRejected() from None
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_MEMBERS_MANAGE,
                    now=now,
                )
                result = self._memberships.mutate(
                    session,
                    tenant_uuid=UUID(auth.tenant_id),
                    actor_user_uuid=UUID(auth.user_id),
                    actor_membership_uuid=UUID(auth.membership_id),
                    actor_session_uuid=UUID(auth.session_id),
                    target_membership_uuid=_uuid(membership_id),
                    expected_target_revision=_positive(expected_row_version),
                    action=selected_action,
                    action_uuid=_uuid(action_id),
                    target_role=selected_role,
                    database_now=now,
                )
            return {
                "membership_id": str(result.membership_uuid),
                "role": result.role.value,
                "status": result.status,
                "row_version": result.row_version,
                "sessions_revoked": result.sessions_revoked,
                "idempotent": result.idempotent,
            }
        except LastActiveAdminError:
            raise TenantLastAdminRejected() from None
        except MemberSeatLimitError:
            raise TenantInvitationSeatLimitRejected() from None
        except MembershipMutationAuthorityError:
            raise TenantMemberMutationVerificationRequired() from None
        except MembershipMutationConflictError:
            raise TenantMemberMutationConflict() from None
        except MembershipMutationInputError:
            raise TenantInvitationInputRejected() from None
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def request_member_mutation_challenge(
        self,
        *,
        flask_request,
        membership_id,
        expected_row_version,
        action,
        action_id,
        target_role=None,
    ):
        try:
            return self._sensitive_members.request_challenge(
                flask_request=flask_request,
                membership_uuid=_uuid(membership_id),
                expected_revision=_positive(expected_row_version),
                action=MembershipMutationAction(action),
                action_uuid=_uuid(action_id),
                target_role=(
                    None if target_role is None else TenantRole(target_role)
                ),
            )
        except SmsSendRejected as exc:
            raise TenantInvitationSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except MembershipMutationConflictError:
            raise TenantMemberMutationConflict() from None
        except (
            MembershipMutationInputError,
            SensitiveActionInputError,
            ValueError,
            TypeError,
        ):
            raise TenantInvitationInputRejected() from None
        except SensitiveActionConflictError:
            raise TenantMemberMutationConflict() from None
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def confirm_member_mutation(
        self,
        *,
        flask_request,
        membership_id,
        expected_row_version,
        action,
        action_id,
        challenge_id,
        plaintext_code,
        target_role=None,
    ):
        try:
            result = self._sensitive_members.confirm(
                flask_request=flask_request,
                membership_uuid=_uuid(membership_id),
                expected_revision=_positive(expected_row_version),
                action=MembershipMutationAction(action),
                action_uuid=_uuid(action_id),
                target_role=(
                    None if target_role is None else TenantRole(target_role)
                ),
                challenge_uuid=_uuid(challenge_id),
                plaintext_code=plaintext_code,
            )
            if result is None:
                raise TenantMemberMutationVerificationRejected()
            return result
        except LastActiveAdminError:
            raise TenantLastAdminRejected() from None
        except MemberSeatLimitError:
            raise TenantInvitationSeatLimitRejected() from None
        except MembershipMutationAuthorityError:
            raise TenantMemberMutationVerificationRejected() from None
        except (
            MembershipMutationConflictError,
            SensitiveActionConflictError,
        ):
            raise TenantMemberMutationConflict() from None
        except (
            MembershipMutationInputError,
            SensitiveActionInputError,
            ValueError,
            TypeError,
        ):
            raise TenantInvitationInputRejected() from None
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def request_admin_challenge(
        self, *, flask_request, raw_phone, role, action_id
    ):
        target_phone = _phone(raw_phone)
        if _role(role) is not InvitationRole.ADMIN:
            raise TenantInvitationInputRejected()

        try:
            return self._sensitive_admin.request_challenge(
                flask_request=flask_request,
                target_phone=target_phone,
                action_uuid=_uuid(action_id),
            )
        except TenantHttpError:
            raise
        except SmsSendRejected as exc:
            raise TenantInvitationSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except SensitiveActionConflictError:
            raise TenantInvitationConflictRejected() from None
        except (SensitiveActionInputError, ValueError, TypeError):
            raise TenantInvitationInputRejected() from None
        except InvitationPersistenceError:
            raise TenantInvitationCredentialRejected() from None
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def create_or_resend(
        self,
        *,
        flask_request,
        raw_phone,
        role,
        expected_row_version,
        action_id=None,
        challenge_id=None,
        plaintext_code=None,
    ):
        target_phone = _phone(raw_phone)
        selected_role = _role(role)
        expected_revision = _optional_positive(expected_row_version)
        if selected_role is InvitationRole.ADMIN and expected_revision is None:
            try:
                result = self._sensitive_admin.confirm(
                    flask_request=flask_request,
                    target_phone=target_phone,
                    action_uuid=_uuid(action_id),
                    challenge_uuid=_uuid(challenge_id),
                    plaintext_code=plaintext_code,
                )
                if result is None:
                    raise TenantInvitationCredentialRejected()
                return result
            except TenantHttpError:
                raise
            except SensitiveActionConflictError:
                raise TenantInvitationConflictRejected() from None
            except (
                SensitiveActionInputError,
                ValueError,
                TypeError,
            ):
                raise TenantInvitationInputRejected() from None
            except Exception as exc:
                raise _translate_persistence(exc) from None
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_MEMBERS_MANAGE,
                    now=now,
                )
                issued = issue_invitation_token(database_now=now)
                result = self._persistence.create_or_resend(
                    session,
                    tenant_uuid=auth.tenant_id,
                    raw_phone=target_phone.e164,
                    role=selected_role,
                    proposed_token=issued.token,
                    proposed_invitation_uuid=uuid4(),
                    proposed_user_uuid=uuid4(),
                    expected_tenant_access_version=auth.tenant_access_version,
                    expected_invitation_row_version=expected_revision,
                )
            return {
                "invitation_id": str(result.invitation_uuid),
                "role": result.role.value,
                "status": result.status,
                "token_generation": result.token_generation,
                "expires_at": _iso(result.expires_at),
                "row_version": result.row_version,
                "created": result.created,
                "rotated": result.rotated,
                "invitation_path": _invitation_path(result),
            }
        except TenantHttpError:
            raise
        except Exception as exc:
            raise _translate_persistence(exc) from None

    def revoke(self, *, flask_request, invitation_id, expected_row_version):
        try:
            selected_id = _uuid(invitation_id)
            revision = _positive(expected_row_version)
            with self._control_database.transaction() as session:
                now = _database_now(session)
                auth = self._tenant_http_boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.TENANT_MEMBERS_MANAGE,
                    now=now,
                )
                owned = session.scalar(
                    sa.select(TenantInvitation.id).where(
                        TenantInvitation.id == str(selected_id),
                        TenantInvitation.tenant_id == auth.tenant_id,
                    )
                )
                if owned is None:
                    raise TenantInvitationConflictRejected()
                result = self._persistence.revoke(
                    session,
                    invitation_uuid=selected_id,
                    expected_invitation_row_version=revision,
                )
            return {
                "invitation_id": str(result.invitation_uuid),
                "status": result.status,
                "row_version": result.row_version,
                "idempotent": result.idempotent,
            }
        except TenantHttpError:
            raise
        except Exception as exc:
            raise _translate_persistence(exc) from None

    def inspect(self, *, invitation_id, token, generation):
        try:
            with self._control_database.transaction() as session:
                credential = self._query.resolve_credential(
                    session,
                    invitation_id=invitation_id,
                    submitted_token=token,
                    submitted_generation=generation,
                    database_now=_database_now(session),
                )
            return _public_credential(credential)
        except InvitationQueryRejected:
            raise TenantInvitationCredentialRejected() from None
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def request_acceptance_challenge(
        self,
        *,
        flask_request,
        invitation_id,
        token,
        generation,
    ):
        def context_factory(session, now):
            credential = self._query.resolve_credential(
                session,
                invitation_id=invitation_id,
                submitted_token=token,
                submitted_generation=generation,
                database_now=now,
            )
            return _accept_context(credential)

        try:
            receipt = self._delivery.issue(
                flask_request=flask_request,
                context_factory=context_factory,
            )
            return _receipt(receipt)
        except InvitationQueryRejected:
            raise TenantInvitationCredentialRejected() from None
        except SmsSendRejected as exc:
            raise TenantInvitationSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except TenantHttpError:
            raise
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None

    def accept(
        self,
        *,
        invitation_id,
        token,
        generation,
        challenge_id,
        plaintext_code,
    ):
        rejected_attempt = None
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                credential = self._query.resolve_credential(
                    session,
                    invitation_id=invitation_id,
                    submitted_token=token,
                    submitted_generation=generation,
                    database_now=now,
                )
                challenge = InvitationChallengeSubmission(
                    challenge_uuid=_uuid(challenge_id),
                    plaintext_code=plaintext_code,
                    root_key=_challenge_root_key(
                        session,
                        challenge_id=challenge_id,
                        root_key_directory=self._root_key_directory,
                    ),
                )
                context = _accept_context(credential)
                try:
                    result = self._persistence.accept(
                        session,
                        invitation_uuid=credential.invitation_uuid,
                        submitted_token=token,
                        submitted_generation=credential.token_generation,
                        expected_invitation_row_version=(
                            credential.invitation_row_version
                        ),
                        expected_winning_tenant_access_version=(
                            credential.tenant_access_version
                        ),
                        proposed_membership_uuid=_membership_uuid(
                            credential.invitation_uuid,
                            challenge.challenge_uuid,
                        ),
                        challenge=challenge,
                    )
                except InvitationChallengeRejectedError:
                    rejected_attempt = (challenge, context)
                    raise
            return {
                "accepted": True,
                "tenant_id": str(result.tenant_uuid),
                "membership_id": str(result.membership_uuid),
                "role": credential.role,
                "superseded_count": result.superseded_count,
                "idempotent": result.idempotent,
            }
        except InvitationChallengeRejectedError:
            self._record_rejected_attempt(rejected_attempt)
            raise TenantInvitationCredentialRejected() from None
        except (InvitationQueryRejected, TenantInvitationCredentialRejected):
            raise TenantInvitationCredentialRejected() from None
        except TenantHttpError:
            raise
        except Exception as exc:
            raise _translate_persistence(exc, public_credential=True) from None

    def _record_rejected_attempt(self, rejected_attempt) -> None:
        if not rejected_attempt:
            return
        challenge, context = rejected_attempt
        try:
            with self._control_database.transaction() as session:
                root_key = _challenge_root_key(
                    session,
                    challenge_id=challenge.challenge_uuid,
                    root_key_directory=self._root_key_directory,
                )
                self._sms.verify_and_consume(
                    session,
                    challenge_id=str(challenge.challenge_uuid),
                    context=context,
                    plaintext_code=challenge.plaintext_code,
                    root_key=root_key,
                    now=_database_now(session),
                )
        except Exception:
            raise TenantInvitationRuntimeUnavailable() from None


def require_tenant_invitation_http_runtime() -> TenantInvitationHttpRuntime:
    runtime = current_app.extensions.get(TENANT_INVITATION_HTTP_RUNTIME_EXTENSION)
    if not isinstance(runtime, TenantInvitationHttpRuntime):
        raise TenantInvitationRuntimeUnavailable()
    return runtime


__all__ = [
    "TENANT_INVITATION_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantInvitationHttpRuntime",
    "TenantInvitationConflictRejected",
    "TenantInvitationCredentialRejected",
    "TenantInvitationHttpRuntime",
    "TenantInvitationInputRejected",
    "TenantInvitationRuntimeUnavailable",
    "TenantInvitationSeatLimitRejected",
    "TenantInvitationSmsRateLimited",
    "require_tenant_invitation_http_runtime",
]
from .admin_sensitive_runtime import AdminInvitationSensitiveRuntime
