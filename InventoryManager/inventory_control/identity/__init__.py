"""Pure control-plane identity primitives."""

from typing import TYPE_CHECKING

from .errors import InvalidOpaqueTokenError, PhoneNormalizationError
from .phone import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    PhoneIdentityNormalizer,
    normalize_tenant_phone,
)
from .tokens import (
    TOKEN_DIGEST_BYTES,
    TOKEN_ENTROPY_BITS,
    TOKEN_ENTROPY_BYTES,
    IssuedOpaqueToken,
    digest_csrf_token,
    digest_session_token,
    issue_csrf_token,
    issue_session_token,
    verify_csrf_token,
    verify_session_token,
)
from .membership_service import (
    AdminPermissionChangeProof,
    LastActiveAdminError,
    MemberSeatLimitError,
    MembershipMutationAction,
    MembershipMutationAuthorityError,
    MembershipMutationConflictError,
    MembershipMutationError,
    MembershipMutationInputError,
    MembershipMutationPlan,
    MembershipMutationResult,
    TenantMembershipService,
    plan_membership_mutation,
)
from .phone_change_service import (
    LockedPhoneChangeScope,
    PhoneChangeAuthorizationProof,
    PhoneChangeConflictError,
    PhoneChangeError,
    PhoneChangeInputError,
    PhoneChangeResult,
    TenantPhoneChangeService,
)
from .session_service import (
    AuthSession,
    CsrfAuthenticationError,
    IssuedAuthSession,
    RevokeAllResult,
    SessionAuthenticationError,
    SessionGateCurrentRead,
    SessionIssueError,
    SessionService,
    SessionTargetNotFound,
    TenantBrowserSessionPolicy,
)
if TYPE_CHECKING:
    from .login_service import (
        TenantLoginCompletion,
        TenantLoginService,
        build_tenant_login_sms_context,
    )


_LAZY_LOGIN_EXPORTS = frozenset({
    "TenantLoginCompletion",
    "TenantLoginService",
    "build_tenant_login_sms_context",
})


def __getattr__(name: str):
    if name not in _LAZY_LOGIN_EXPORTS:
        raise AttributeError(name)
    from . import login_service

    resolved = getattr(login_service, name)
    globals()[name] = resolved
    return resolved

__all__ = [
    "AdminPermissionChangeProof",
    "CN_MOBILE_METADATA_VERSION",
    "AuthSession",
    "CsrfAuthenticationError",
    "InvalidOpaqueTokenError",
    "IssuedOpaqueToken",
    "IssuedAuthSession",
    "LastActiveAdminError",
    "MemberSeatLimitError",
    "MembershipMutationAction",
    "MembershipMutationAuthorityError",
    "MembershipMutationConflictError",
    "MembershipMutationError",
    "MembershipMutationInputError",
    "MembershipMutationPlan",
    "MembershipMutationResult",
    "LockedPhoneChangeScope",
    "PHONE_NORMALIZATION_VERSION",
    "PhoneIdentityNormalizer",
    "PhoneChangeAuthorizationProof",
    "PhoneChangeConflictError",
    "PhoneChangeError",
    "PhoneChangeInputError",
    "PhoneChangeResult",
    "PhoneNormalizationError",
    "RevokeAllResult",
    "SessionAuthenticationError",
    "SessionGateCurrentRead",
    "SessionIssueError",
    "SessionService",
    "SessionTargetNotFound",
    "TenantBrowserSessionPolicy",
    "TenantLoginCompletion",
    "TenantLoginService",
    "TenantMembershipService",
    "TenantPhoneChangeService",
    "TOKEN_DIGEST_BYTES",
    "TOKEN_ENTROPY_BITS",
    "TOKEN_ENTROPY_BYTES",
    "digest_csrf_token",
    "digest_session_token",
    "issue_csrf_token",
    "issue_session_token",
    "normalize_tenant_phone",
    "plan_membership_mutation",
    "verify_csrf_token",
    "verify_session_token",
    "build_tenant_login_sms_context",
]
