"""Fail-closed Flask boundary for tenant browser authentication.

The boundary deliberately owns neither the control-database transaction nor
the application route.  A route supplies its caller-owned ``Session`` and
receives an ``AuthContext`` containing only trusted identifiers and current
authorization facts.  Raw browser credentials never leave this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from flask import Request, Response
from sqlalchemy.orm import Session

from app.tenancy import TenantContext, TenantContextSource
from inventory_control.domain.access_policy import (
    has_tenant_capability_for_gate,
)
from inventory_control.domain.rbac import Capability, TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.identity import (
    AuthSession,
    CsrfAuthenticationError,
    InvalidOpaqueTokenError,
    SessionAuthenticationError,
    SessionService,
    digest_session_token,
)


TENANT_SESSION_COOKIE_NAME = "__Host-inventory_tenant_session"
TENANT_CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Trusted request identity with no client-carried bearer material."""

    session_id: str
    user_id: str
    membership_id: str
    tenant_id: str
    role: TenantRole
    user_auth_version: int
    tenant_access_version: int
    tenant_timezone: str
    effective_gate: EffectiveTenantGate

    @classmethod
    def from_auth_session(cls, auth: AuthSession) -> "AuthContext":
        return cls(
            session_id=auth.session_id,
            user_id=auth.user_id,
            membership_id=auth.membership_id,
            tenant_id=auth.tenant_id,
            role=auth.role,
            user_auth_version=auth.user_auth_version,
            tenant_access_version=auth.tenant_access_version,
            tenant_timezone=auth.tenant_timezone,
            effective_gate=auth.effective_gate,
        )


class TenantHttpError(RuntimeError):
    """A fixed public HTTP rejection without lookup or credential details."""

    status_code: int
    code: str
    public_message: str

    def __init__(self) -> None:
        super().__init__(self.public_message)


class TenantAuthenticationRequired(TenantHttpError):
    status_code = 401
    code = "TENANT_SESSION_INVALID"
    public_message = "Authentication is required."


class TenantCapabilityDenied(TenantHttpError):
    status_code = 403
    code = "TENANT_CAPABILITY_DENIED"
    public_message = "The requested action is not permitted."


class TenantCsrfDenied(TenantHttpError):
    status_code = 403
    code = "CSRF_INVALID"
    public_message = "The CSRF proof is invalid."


def active_tenant_context(
    auth_context: AuthContext,
    *,
    request_id: str,
) -> TenantContext:
    """Convert trusted active browser identity into tenant-routing authority.

    Restricted expired or suspended sessions intentionally retain a small HTTP
    surface, but that surface must never become authority to open the tenant
    business database.  UUID parsing also fails closed if trusted control-plane
    identity data is malformed.
    """

    if not isinstance(auth_context, AuthContext):
        raise TypeError("auth_context must be an AuthContext")
    if auth_context.effective_gate is not EffectiveTenantGate.ACTIVE:
        raise TenantCapabilityDenied()
    try:
        tenant_id = UUID(auth_context.tenant_id)
        UUID(auth_context.user_id)
        UUID(auth_context.session_id)
    except (TypeError, ValueError, AttributeError):
        raise TenantAuthenticationRequired() from None

    try:
        return TenantContext(
            tenant_id=tenant_id,
            access_version=auth_context.tenant_access_version,
            source=TenantContextSource.WEB_SESSION,
            principal_ref=f"user:{auth_context.user_id}",
            source_ref=f"session:{auth_context.session_id}",
            request_id=request_id,
        )
    except (TypeError, ValueError):
        raise TenantAuthenticationRequired() from None


class TenantHttpBoundary:
    """Resolve and authorize one tenant request inside a supplied transaction."""

    def __init__(self, session_service: SessionService) -> None:
        if not isinstance(session_service, SessionService):
            raise TypeError("session_service must be a SessionService")
        self._session_service = session_service

    @property
    def session_service(self) -> SessionService:
        """Expose the exact service used by a composed control-only route."""

        return self._session_service

    def authenticate(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        now: datetime | None = None,
        ip_summary: str | None = None,
    ) -> AuthContext:
        """Resolve the sole fixed host Cookie into a bearer-free context."""

        auth = self._resolve(
            control_session,
            flask_request,
            now=now,
            ip_summary=ip_summary,
        )
        return AuthContext.from_auth_session(auth)

    def authorize(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        capability: Capability,
        now: datetime | None = None,
        ip_summary: str | None = None,
    ) -> AuthContext:
        """Authenticate, refresh mutation proofs, and enforce one capability.

        Every method outside GET/HEAD/OPTIONS verifies the independent CSRF
        proof and re-reduces the effective tenant gate in this same
        caller-owned transaction before applying authorization.  The fresh
        gate, rather than the earlier authentication snapshot, is returned to
        the route.  Callers therefore cannot accidentally mark POST/PUT/PATCH/
        DELETE (or an unknown extension method) as a safe request.
        """

        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability")

        auth = self._resolve(
            control_session,
            flask_request,
            now=now,
            ip_summary=ip_summary,
        )
        context = AuthContext.from_auth_session(auth)

        if flask_request.method.upper() not in _SAFE_HTTP_METHODS:
            csrf_values = flask_request.headers.getlist(TENANT_CSRF_HEADER_NAME)
            presented_csrf: object = (
                csrf_values[0] if len(csrf_values) == 1 else None
            )
            try:
                fresh_gate = self._session_service.verify_csrf(
                    control_session,
                    auth=auth,
                    presented_csrf=presented_csrf,
                    now=now,
                )
            except CsrfAuthenticationError:
                raise TenantCsrfDenied() from None
            context = replace(context, effective_gate=fresh_gate)

        if not has_tenant_capability_for_gate(
            role=context.role,
            gate=context.effective_gate,
            capability=capability,
        ):
            raise TenantCapabilityDenied()
        return context

    def _resolve(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        now: datetime | None,
        ip_summary: str | None,
    ) -> AuthSession:
        cookie_values = flask_request.cookies.getlist(TENANT_SESSION_COOKIE_NAME)
        presented_token: object = (
            cookie_values[0] if len(cookie_values) == 1 else None
        )
        try:
            return self._session_service.resolve(
                control_session,
                presented_token,
                now=now,
                ip_summary=ip_summary,
            )
        except SessionAuthenticationError:
            raise TenantAuthenticationRequired() from None


def set_tenant_session_cookie(
    response: Response,
    session_token: str,
    *,
    max_age: int | None = None,
) -> Response:
    """Set the fixed host-only tenant Cookie with invariant attributes."""

    try:
        digest_session_token(session_token)
    except (InvalidOpaqueTokenError, TypeError):
        raise ValueError(
            "session_token must be a valid opaque session token"
        ) from None
    if max_age is not None and (not isinstance(max_age, int) or max_age <= 0):
        raise ValueError("max_age must be a positive integer or None")
    response.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        session_token,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return mark_private_no_store(response)


def clear_tenant_session_cookie(response: Response) -> Response:
    """Expire the fixed tenant Cookie without adding a Domain attribute."""

    response.delete_cookie(
        TENANT_SESSION_COOKIE_NAME,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return mark_private_no_store(response)


def mark_private_no_store(response: Response) -> Response:
    """Prevent browser or intermediary persistence of a sensitive response."""

    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def tenant_http_error_response(error: TenantHttpError) -> Response:
    """Render a stable, no-store error body containing no request material."""

    if not isinstance(error, TenantHttpError):
        raise TypeError("error must be a TenantHttpError")
    payload = {
        "error": {
            "code": error.code,
            "message": error.public_message,
        }
    }
    response = Response(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        status=error.status_code,
        content_type="application/json",
    )
    return mark_private_no_store(response)
