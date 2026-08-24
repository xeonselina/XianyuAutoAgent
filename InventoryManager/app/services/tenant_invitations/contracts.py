"""Stable public contracts for the tenant invitation HTTP boundary."""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from flask import Request

from inventory_control.tenant_http import TenantHttpError


TENANT_INVITATION_HTTP_RUNTIME_EXTENSION = "inventory_tenant_invitation_http_runtime"


class TenantInvitationRuntimeUnavailable(RuntimeError):
    pass


class TenantInvitationInputRejected(TenantHttpError):
    status_code = 400
    code = "INVITATION_INPUT_INVALID"
    public_message = "邀请请求格式无效。"


class TenantInvitationCredentialRejected(TenantHttpError):
    status_code = 404
    code = "INVITATION_UNAVAILABLE"
    public_message = "邀请无效、已过期或已失效。"


class TenantInvitationConflictRejected(TenantHttpError):
    status_code = 409
    code = "INVITATION_CONFLICT"
    public_message = "邀请状态已变化，请刷新后重试。"


class TenantInvitationSeatLimitRejected(TenantHttpError):
    status_code = 409
    code = "MEMBER_SEAT_LIMIT_EXCEEDED"
    public_message = "有效成员和待接受邀请已达到 10 个。"


class TenantMemberMutationVerificationRequired(TenantHttpError):
    status_code = 403
    code = "MEMBER_MUTATION_VERIFICATION_REQUIRED"
    public_message = "此成员变更需要当前管理员完成动作专用短信验证。"


class TenantMemberMutationVerificationRejected(TenantHttpError):
    status_code = 403
    code = "MEMBER_MUTATION_VERIFICATION_REJECTED"
    public_message = (
        "验证码无效、已过期或与当前成员变更不匹配。"
    )


class TenantMemberMutationConflict(TenantHttpError):
    status_code = 409
    code = "MEMBER_MUTATION_CONFLICT"
    public_message = "成员状态已变化，请刷新后重试。"


class TenantLastAdminRejected(TenantHttpError):
    status_code = 409
    code = "LAST_ACTIVE_ADMIN_REQUIRED"
    public_message = "租户必须至少保留一名有效管理员。"


class TenantInvitationSmsRateLimited(TenantHttpError):
    status_code = 429
    code = "TENANT_SMS_RATE_LIMITED"
    public_message = "短信验证码请求过于频繁，请稍后重试。"

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = max(1, retry_after_seconds)


@runtime_checkable
class TenantInvitationHttpRuntime(Protocol):
    def list_members(
        self, *, flask_request: Request
    ) -> Mapping[str, object]: ...

    def mutate_member(
        self,
        *,
        flask_request: Request,
        membership_id: object,
        expected_row_version: object,
        action: object,
        action_id: object,
        target_role: object = None,
    ) -> Mapping[str, object]: ...

    def request_member_mutation_challenge(
        self,
        *,
        flask_request: Request,
        membership_id: object,
        expected_row_version: object,
        action: object,
        action_id: object,
        target_role: object = None,
    ) -> Mapping[str, object]: ...

    def confirm_member_mutation(
        self,
        *,
        flask_request: Request,
        membership_id: object,
        expected_row_version: object,
        action: object,
        action_id: object,
        challenge_id: object,
        plaintext_code: object,
        target_role: object = None,
    ) -> Mapping[str, object]: ...

    def request_admin_challenge(
        self,
        *,
        flask_request: Request,
        raw_phone: object,
        role: object,
        action_id: object,
    ) -> Mapping[str, object]: ...

    def create_or_resend(
        self,
        *,
        flask_request: Request,
        raw_phone: object,
        role: object,
        expected_row_version: object,
        action_id: object = None,
        challenge_id: object = None,
        plaintext_code: object = None,
    ) -> Mapping[str, object]: ...

    def revoke(
        self,
        *,
        flask_request: Request,
        invitation_id: object,
        expected_row_version: object,
    ) -> Mapping[str, object]: ...

    def inspect(
        self, *, invitation_id: object, token: object, generation: object
    ) -> Mapping[str, object]: ...

    def request_acceptance_challenge(
        self,
        *,
        flask_request: Request,
        invitation_id: object,
        token: object,
        generation: object,
    ) -> Mapping[str, object]: ...

    def accept(
        self,
        *,
        invitation_id: object,
        token: object,
        generation: object,
        challenge_id: object,
        plaintext_code: object,
    ) -> Mapping[str, object]: ...


__all__ = [
    "TENANT_INVITATION_HTTP_RUNTIME_EXTENSION",
    "TenantInvitationConflictRejected",
    "TenantInvitationCredentialRejected",
    "TenantInvitationHttpRuntime",
    "TenantInvitationInputRejected",
    "TenantInvitationRuntimeUnavailable",
    "TenantInvitationSeatLimitRejected",
    "TenantInvitationSmsRateLimited",
    "TenantLastAdminRejected",
    "TenantMemberMutationConflict",
    "TenantMemberMutationVerificationRequired",
    "TenantMemberMutationVerificationRejected",
]
