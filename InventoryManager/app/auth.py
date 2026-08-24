"""Minimal SMS authentication, session, CSRF, and fixed-role helpers."""

import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, Optional

from flask import g, request
from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.control.models import (
    AuthSession,
    PlatformAdmin,
    SmsLoginCode,
    Tenant,
    TenantMember,
)
from app.crypto import digest_sms_code, hash_token
from app.utils.response import error


LOGGER = logging.getLogger(__name__)
TENANT_SESSION_SECONDS = 7 * 24 * 60 * 60
PLATFORM_SESSION_SECONDS = 12 * 60 * 60
SMS_CODE_MINUTES = 5
SMS_MAX_ATTEMPTS = 5
SMS_RETENTION_DAYS = 7
_PHONE_PATTERN = re.compile(r"^1[3-9][0-9]{9}$")


@dataclass(frozen=True)
class SmsSendResult:
    ok: bool
    code: str


@dataclass(frozen=True)
class SessionCredentials:
    raw_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class TenantLogin:
    member: TenantMember
    tenant: Tenant
    credentials: SessionCredentials


@dataclass(frozen=True)
class TenantSessionIdentity:
    auth_session: AuthSession
    member: TenantMember
    tenant: Tenant


@dataclass(frozen=True)
class PlatformSessionIdentity:
    auth_session: AuthSession
    admin: PlatformAdmin


class SmsRateLimitExceeded(Exception):
    def __init__(self, scope):
        super().__init__(scope)
        self.scope = scope


class FakeSmsSender:
    """Deterministic in-process transport for tests and local development."""

    def __init__(self, result=None):
        self.result = result or SmsSendResult(ok=True, code="Ok")
        self.last_phone = None
        self.last_code = None
        self.last_minutes = None
        self.send_count = 0

    def send_code(self, phone_e164, code, minutes):
        self.last_phone = phone_e164
        self.last_code = code
        self.last_minutes = minutes
        self.send_count += 1
        return self.result


class TencentSmsSender:
    """Narrow Tencent Cloud SMS adapter used by the authentication service."""

    def __init__(
        self,
        secret_id,
        secret_key,
        sdk_app_id,
        sign_name,
        template_id,
        region="ap-guangzhou",
        client=None,
    ):
        self.sdk_app_id = sdk_app_id
        self.sign_name = sign_name
        self.template_id = template_id
        if client is None:
            from tencentcloud.common.credential import Credential
            from tencentcloud.sms.v20210111.sms_client import SmsClient

            client = SmsClient(
                Credential(secret_id, secret_key),
                region,
            )
        self.client = client

    def send_code(self, phone_e164, code, minutes):
        from tencentcloud.sms.v20210111.models import SendSmsRequest

        sms_request = SendSmsRequest()
        sms_request.PhoneNumberSet = [phone_e164]
        sms_request.SmsSdkAppId = self.sdk_app_id
        sms_request.SignName = self.sign_name
        sms_request.TemplateId = self.template_id
        sms_request.TemplateParamSet = [code, str(minutes)]
        response = self.client.SendSms(sms_request)
        statuses = response.SendStatusSet or []
        response_code = statuses[0].Code if statuses else "EmptyResponse"
        return SmsSendResult(
            ok=response_code == "Ok",
            code=response_code,
        )


def normalize_china_phone(raw_phone):
    if not isinstance(raw_phone, str):
        raise ValueError("phone must be a mainland China mobile number")
    normalized = re.sub(r"[\s()\-]", "", raw_phone)
    if normalized.startswith("0086"):
        normalized = normalized[4:]
    elif normalized.startswith("+86"):
        normalized = normalized[3:]
    elif normalized.startswith("86") and len(normalized) == 13:
        normalized = normalized[2:]
    if not _PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("phone must be a mainland China mobile number")
    return f"+86{normalized}"


def mask_phone(phone_e164):
    return f"{phone_e164[:6]}****{phone_e164[-4:]}"


def _utcnow():
    return datetime.utcnow()


def _session_seconds(kind):
    if kind == "tenant":
        return TENANT_SESSION_SECONDS
    if kind == "platform":
        return PLATFORM_SESSION_SECONDS
    raise ValueError("session kind must be tenant or platform")


def create_auth_session(
    session,
    kind,
    subject_id,
    tenant_id=None,
    now=None,
):
    now = now or _utcnow()
    if kind == "tenant" and tenant_id is None:
        raise ValueError("tenant session requires tenant_id")
    if kind == "platform" and tenant_id is not None:
        raise ValueError("platform session cannot have tenant_id")

    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=_session_seconds(kind))
    session.add(
        AuthSession(
            kind=kind,
            subject_id=subject_id,
            tenant_id=tenant_id,
            token_hash=hash_token(raw_token),
            csrf_token_hash=hash_token(csrf_token),
            expires_at=expires_at,
            created_at=now,
            last_seen_at=now,
        )
    )
    return SessionCredentials(
        raw_token=raw_token,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


def session_cookie_options(kind, secure):
    return {
        "httponly": True,
        "samesite": "Lax",
        "secure": bool(secure),
        "path": "/" if kind == "tenant" else "/platform",
        "max_age": _session_seconds(kind),
    }


def csrf_matches(auth_session, raw_token):
    if not raw_token:
        return False
    return hmac.compare_digest(
        auth_session.csrf_token_hash,
        hash_token(raw_token),
    )


def resolve_tenant_session(store, raw_token, now=None):
    if not raw_token:
        return None
    now = now or _utcnow()
    with store.session() as session:
        row = session.execute(
            select(AuthSession, TenantMember, Tenant)
            .select_from(AuthSession)
            .join(
                TenantMember,
                and_(
                    TenantMember.id == AuthSession.subject_id,
                    TenantMember.tenant_id == AuthSession.tenant_id,
                ),
            )
            .join(Tenant, Tenant.id == AuthSession.tenant_id)
            .where(
                AuthSession.kind == "tenant",
                AuthSession.token_hash == hash_token(raw_token),
                AuthSession.expires_at > now,
            )
        ).one_or_none()
        if row is None:
            return None
        auth_session, member, tenant = row
        if member.status != "active":
            session.delete(auth_session)
            return None
        auth_session.last_seen_at = now
        return TenantSessionIdentity(
            auth_session=auth_session,
            member=member,
            tenant=tenant,
        )


def resolve_platform_session(store, raw_token, now=None):
    if not raw_token:
        return None
    now = now or _utcnow()
    with store.session() as session:
        row = session.execute(
            select(AuthSession, PlatformAdmin)
            .select_from(AuthSession)
            .join(
                PlatformAdmin,
                PlatformAdmin.id == AuthSession.subject_id,
            )
            .where(
                AuthSession.kind == "platform",
                AuthSession.tenant_id.is_(None),
                AuthSession.token_hash == hash_token(raw_token),
                AuthSession.expires_at > now,
            )
        ).one_or_none()
        if row is None:
            return None
        auth_session, admin = row
        auth_session.last_seen_at = now
        return PlatformSessionIdentity(
            auth_session=auth_session,
            admin=admin,
        )


def rotate_csrf_token(store, auth_session_id, now=None):
    now = now or _utcnow()
    csrf_token = secrets.token_urlsafe(32)
    with store.session() as session:
        auth_session = session.get(AuthSession, auth_session_id)
        if auth_session is None or auth_session.expires_at <= now:
            return None
        auth_session.csrf_token_hash = hash_token(csrf_token)
        auth_session.last_seen_at = now
    return csrf_token


def revoke_auth_session(store, auth_session_id):
    with store.session() as session:
        auth_session = session.get(AuthSession, auth_session_id)
        if auth_session is not None:
            session.delete(auth_session)


def require_csrf(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth_session = getattr(g, "auth_session", None)
        if auth_session is None or not csrf_matches(
            auth_session,
            request.headers.get("X-CSRF-Token"),
        ):
            return error(
                "CSRF token 无效",
                status_code=403,
                code="CSRF_INVALID",
            ).to_flask_response()
        return view(*args, **kwargs)

    return wrapped


def require_role(required_role):
    if required_role != "admin":
        raise ValueError("only the fixed admin role can be required")

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            member = getattr(g, "member", None)
            if member is None:
                return error(
                    "需要租户登录",
                    status_code=401,
                    code="AUTH_REQUIRED",
                ).to_flask_response()
            if member.role != "admin":
                return error(
                    "没有管理员权限",
                    status_code=403,
                    code="FORBIDDEN",
                ).to_flask_response()
            return view(*args, **kwargs)

        return wrapped

    return decorator


class AuthService:
    def __init__(
        self,
        store,
        master_key,
        sender,
        fixed_code=None,
        now: Optional[Callable[[], datetime]] = None,
        logger=None,
    ):
        self.store = store
        self.master_key = master_key
        self.sender = sender
        self.fixed_code = fixed_code
        self.now = now or _utcnow
        self.logger = logger or LOGGER

    def _check_rate_limits(self, session, phone, requested_ip, now):
        limits = (
            (
                "phone_minute",
                SmsLoginCode.phone == phone,
                now - timedelta(seconds=60),
                1,
            ),
            (
                "phone_hour",
                SmsLoginCode.phone == phone,
                now - timedelta(hours=1),
                5,
            ),
            (
                "phone_day",
                SmsLoginCode.phone == phone,
                now - timedelta(days=1),
                10,
            ),
            (
                "ip_hour",
                SmsLoginCode.requested_ip == requested_ip,
                now - timedelta(hours=1),
                30,
            ),
        )
        for scope, identity_filter, cutoff, maximum in limits:
            cutoff = cutoff.replace(microsecond=0)
            count = session.scalar(
                select(func.count(SmsLoginCode.id)).where(
                    identity_filter,
                    SmsLoginCode.created_at >= cutoff,
                )
            )
            if count >= maximum:
                raise SmsRateLimitExceeded(scope)

    def request_code(self, raw_phone, requested_ip):
        phone = normalize_china_phone(raw_phone)
        now = self.now()
        requested_ip = (requested_ip or "unknown")[:45]
        code = self.fixed_code or f"{secrets.randbelow(1_000_000):06d}"

        lock_names = (
            f"sms-phone-{hash_token(phone)[:48]}",
            f"sms-ip-{hash_token(requested_ip)[:48]}",
        )
        try:
            with self.store.locked_session(
                lock_names,
                timeout=0,
            ) as session:
                code_row_id, should_send = self._persist_code_request(
                    session,
                    phone,
                    requested_ip,
                    code,
                    now,
                )
        except TimeoutError as exc:
            raise SmsRateLimitExceeded("busy") from exc

        self._best_effort_cleanup(now)

        if not should_send:
            return None

        try:
            result = self.sender.send_code(
                phone,
                code,
                SMS_CODE_MINUTES,
            )
        except Exception as exc:
            self.logger.warning(
                "SMS send failed for %s (%s)",
                mask_phone(phone),
                type(exc).__name__,
            )
            return None

        if not (result.ok and result.code == "Ok"):
            self.logger.warning(
                "SMS provider rejected send for %s",
                mask_phone(phone),
            )
            return None

        try:
            with self.store.session() as session:
                code_row = session.get(SmsLoginCode, code_row_id)
                if code_row is not None:
                    code_row.send_succeeded = True
        except Exception as exc:
            self.logger.warning(
                "Unable to persist SMS send success for %s (%s)",
                mask_phone(phone),
                type(exc).__name__,
            )
        return None

    def _best_effort_cleanup(self, now):
        try:
            with self.store.maintenance_locked_session(
                ("sms-retention-cleanup",),
                timeout=0,
            ) as session:
                stale_ids = session.scalars(
                    select(SmsLoginCode.id)
                    .where(
                        SmsLoginCode.created_at
                        < (
                            now - timedelta(days=SMS_RETENTION_DAYS)
                        ).replace(microsecond=0)
                    )
                    .order_by(SmsLoginCode.id)
                    .limit(500)
                ).all()
                if stale_ids:
                    locked_ids = session.scalars(
                        select(SmsLoginCode.id)
                        .where(SmsLoginCode.id.in_(stale_ids))
                        .with_for_update(nowait=True)
                    ).all()
                    session.execute(
                        delete(SmsLoginCode).where(
                            SmsLoginCode.id.in_(locked_ids)
                        )
                    )
        except (TimeoutError, SQLAlchemyError) as exc:
            self.logger.warning(
                "SMS retention cleanup skipped (%s)",
                type(exc).__name__,
            )

    def _persist_code_request(
        self,
        session,
        phone,
        requested_ip,
        code,
        now,
    ):
        self._check_rate_limits(session, phone, requested_ip, now)
        member = session.scalar(
            select(TenantMember).where(
                TenantMember.phone == phone,
                TenantMember.status == "active",
            )
        )
        code_row = SmsLoginCode(
            phone=phone,
            code_digest=digest_sms_code(phone, code, self.master_key),
            requested_ip=requested_ip,
            send_succeeded=False,
            attempt_count=0,
            expires_at=now + timedelta(minutes=SMS_CODE_MINUTES),
            created_at=now,
        )
        session.add(code_row)
        session.flush()
        return code_row.id, member is not None

    def verify_code(self, raw_phone, code):
        try:
            phone = normalize_china_phone(raw_phone)
        except ValueError:
            return None
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            return None

        now = self.now()
        with self.store.session() as session:
            code_row = session.scalar(
                select(SmsLoginCode)
                .where(SmsLoginCode.phone == phone)
                .order_by(SmsLoginCode.created_at.desc(),
                          SmsLoginCode.id.desc())
                .with_for_update()
                .limit(1)
            )
            if (
                code_row is None
                or code_row.consumed_at is not None
                or code_row.expires_at <= now
                or not code_row.send_succeeded
                or code_row.attempt_count >= SMS_MAX_ATTEMPTS
            ):
                return None

            expected_digest = digest_sms_code(
                phone,
                code,
                self.master_key,
            )
            if not hmac.compare_digest(
                code_row.code_digest,
                expected_digest,
            ):
                code_row.attempt_count += 1
                return None

            code_row.consumed_at = now
            row = session.execute(
                select(TenantMember, Tenant)
                .join(Tenant, Tenant.id == TenantMember.tenant_id)
                .where(
                    TenantMember.phone == phone,
                    TenantMember.status == "active",
                )
            ).one_or_none()
            if row is None:
                return None
            member, tenant = row
            credentials = create_auth_session(
                session,
                kind="tenant",
                subject_id=member.id,
                tenant_id=tenant.id,
                now=now,
            )
            return TenantLogin(
                member=member,
                tenant=tenant,
                credentials=credentials,
            )
