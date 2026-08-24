"""Independent Flask Cookie, CSRF, and capability boundary for platform admins."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from flask import Request, Response
from sqlalchemy.orm import Session

from inventory_control.domain.rbac import (
    Capability,
    PlatformRole,
    has_platform_capability,
)
from inventory_control.platform_identity import (
    PlatformAdminSessionService,
    PlatformAuthSession,
    PlatformCredentialError,
    PlatformCsrfAuthenticationError,
    PlatformSessionAuthenticationError,
    digest_platform_session_token,
)


PLATFORM_SESSION_COOKIE_NAME = "__Secure-inventory_platform_session"
PLATFORM_DEVICE_COOKIE_NAME = "__Secure-inventory_platform_device"
PLATFORM_CSRF_HEADER_NAME = "X-Platform-CSRF-Token"
PLATFORM_SETUP_HEADER_NAME = "X-Platform-Setup-Token"
_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEVICE_ID = re.compile(r"impd1_[A-Za-z0-9_-]{43}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class PlatformAuthContext:
    session_id: str
    platform_admin_id: str
    username_canonical: str
    role: PlatformRole
    admin_auth_version: int
    admin_setup_version: int
    mfa_method: str
    mfa_verified_at: datetime

    @classmethod
    def from_auth_session(cls, auth: PlatformAuthSession) -> "PlatformAuthContext":
        return cls(
            session_id=auth.session_id,
            platform_admin_id=auth.platform_admin_id,
            username_canonical=auth.username_canonical,
            role=PlatformRole.PLATFORM_ADMIN,
            admin_auth_version=auth.admin_auth_version,
            admin_setup_version=auth.admin_setup_version,
            mfa_method=auth.mfa_method,
            mfa_verified_at=auth.mfa_verified_at,
        )


class PlatformHttpError(RuntimeError):
    status_code: int
    code: str
    public_message: str

    def __init__(self) -> None:
        super().__init__(self.public_message)


class PlatformAuthenticationRequired(PlatformHttpError):
    status_code = 401
    code = "PLATFORM_SESSION_INVALID"
    public_message = "Platform authentication is required."


class PlatformCapabilityDenied(PlatformHttpError):
    status_code = 403
    code = "PLATFORM_CAPABILITY_DENIED"
    public_message = "The requested platform action is not permitted."


class PlatformCsrfDenied(PlatformHttpError):
    status_code = 403
    code = "PLATFORM_CSRF_INVALID"
    public_message = "The platform CSRF proof is invalid."


class PlatformHttpBoundary:
    def __init__(self, session_service: PlatformAdminSessionService) -> None:
        if not isinstance(session_service, PlatformAdminSessionService):
            raise TypeError(
                "session_service must be a PlatformAdminSessionService"
            )
        self._session_service = session_service

    @property
    def session_service(self) -> PlatformAdminSessionService:
        return self._session_service

    def authenticate(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        now: datetime | None = None,
        ip_summary: str | None = None,
    ) -> PlatformAuthContext:
        auth = self._resolve(
            control_session,
            flask_request,
            now=now,
            ip_summary=ip_summary,
        )
        return PlatformAuthContext.from_auth_session(auth)

    def authorize(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        capability: Capability,
        now: datetime | None = None,
        ip_summary: str | None = None,
    ) -> PlatformAuthContext:
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability")
        auth = self._resolve(
            control_session,
            flask_request,
            now=now,
            ip_summary=ip_summary,
        )
        if flask_request.method.upper() not in _SAFE_HTTP_METHODS:
            csrf_values = flask_request.headers.getlist(
                PLATFORM_CSRF_HEADER_NAME
            )
            presented_csrf: object = (
                csrf_values[0] if len(csrf_values) == 1 else None
            )
            try:
                self._session_service.verify_csrf(
                    control_session,
                    auth=auth,
                    presented_csrf=presented_csrf,
                    now=now,
                )
            except PlatformCsrfAuthenticationError:
                raise PlatformCsrfDenied() from None
        if not has_platform_capability(
            PlatformRole.PLATFORM_ADMIN, capability
        ):
            raise PlatformCapabilityDenied()
        return PlatformAuthContext.from_auth_session(auth)

    def _resolve(
        self,
        control_session: Session,
        flask_request: Request,
        *,
        now: datetime | None,
        ip_summary: str | None,
    ) -> PlatformAuthSession:
        cookie_values = flask_request.cookies.getlist(
            PLATFORM_SESSION_COOKIE_NAME
        )
        token: object = cookie_values[0] if len(cookie_values) == 1 else None
        try:
            return self._session_service.resolve(
                control_session,
                token,
                ip_summary=ip_summary,
                now=now,
            )
        except PlatformSessionAuthenticationError:
            raise PlatformAuthenticationRequired() from None


def issue_platform_device_id() -> str:
    return "impd1_" + secrets.token_urlsafe(32)


def resolve_platform_device_id(request: Request) -> tuple[str, bool]:
    values = request.cookies.getlist(PLATFORM_DEVICE_COOKIE_NAME)
    if len(values) == 1 and _DEVICE_ID.fullmatch(values[0]) is not None:
        return values[0], False
    return issue_platform_device_id(), True


def set_platform_session_cookie(
    response: Response,
    session_token: str,
) -> Response:
    try:
        digest_platform_session_token(session_token)
    except (PlatformCredentialError, TypeError, ValueError):
        raise ValueError("session_token must be a platform bearer") from None
    response.set_cookie(
        PLATFORM_SESSION_COOKIE_NAME,
        session_token,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/platform",
    )
    return mark_platform_private_no_store(response)


def clear_platform_session_cookie(response: Response) -> Response:
    response.delete_cookie(
        PLATFORM_SESSION_COOKIE_NAME,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/platform",
    )
    return mark_platform_private_no_store(response)


def set_platform_device_cookie(
    response: Response,
    device_id: str,
    *,
    max_age_seconds: int,
) -> Response:
    if _DEVICE_ID.fullmatch(device_id) is None:
        raise ValueError("device_id is invalid")
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int)
        or not 1 <= max_age_seconds <= 31_536_000
    ):
        raise ValueError("device Cookie max age is invalid")
    response.set_cookie(
        PLATFORM_DEVICE_COOKIE_NAME,
        device_id,
        max_age=max_age_seconds,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/platform",
    )
    return mark_platform_private_no_store(response)


def mark_platform_private_no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def platform_http_error_response(error: PlatformHttpError) -> Response:
    if not isinstance(error, PlatformHttpError):
        raise TypeError("error must be a PlatformHttpError")
    response = Response(
        json.dumps(
            {
                "error": {
                    "code": error.code,
                    "message": error.public_message,
                }
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        status=error.status_code,
        content_type="application/json",
    )
    return mark_platform_private_no_store(response)
