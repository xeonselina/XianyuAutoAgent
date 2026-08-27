"""Platform administrator authentication, tenant API, and local CLI."""

import json
from datetime import datetime, timedelta, timezone

import click
import pyotp
from flask import Blueprint, current_app, g, make_response, request
from flask.cli import with_appcontext
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth import (
    create_auth_session,
    csrf_matches,
    normalize_china_phone,
    refresh_csrf_token,
    resolve_platform_session,
    revoke_auth_session,
    session_cookie_options,
)
from app.control.models import PlatformAdmin, Tenant, TenantMember
from app.crypto import hash_token
from app.provisioning import (
    TenantNotFound,
    TenantPhoneConflict,
    business_migration_head,
    validate_tenant_expiration,
)
from app.utils.response import error, success


bp = Blueprint("platform_api", __name__, url_prefix="/platform")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_TENANT_PATCH_FIELDS = {
    "name",
    "admin_phone",
    "status",
    "expires_at",
    "extend_days",
}


def _platform_auth_error():
    return error(
        "平台会话无效或已过期",
        status_code=401,
        code="AUTH_REQUIRED",
    ).to_flask_response()


def _invalid_request(message):
    return error(
        message,
        status_code=400,
        code="INVALID_REQUEST",
    ).to_flask_response()


def _control_store():
    return current_app.extensions.get("control_store")


@bp.before_request
def authenticate_platform_request():
    if request.method == "OPTIONS":
        return None
    if request.path == "/platform/auth/login":
        return None

    store = _control_store()
    if store is None:
        return error(
            "平台认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()
    identity = resolve_platform_session(
        store,
        request.cookies.get("platform_session"),
    )
    if identity is None:
        return _platform_auth_error()

    g.platform_admin = identity.admin
    g.auth_session = identity.auth_session
    if request.method not in _SAFE_METHODS and not csrf_matches(
        identity.auth_session,
        request.headers.get("X-CSRF-Token"),
    ):
        return error(
            "CSRF token 无效",
            status_code=403,
            code="CSRF_INVALID",
        ).to_flask_response()
    return None


def _admin_payload(admin, csrf_token):
    return {
        "csrf_token": csrf_token,
        "admin": {
            "id": admin.id,
            "username": admin.username,
        },
    }


def _format_datetime(value):
    return value.isoformat() + "Z"


def _parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expires_at must be an ISO datetime")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO datetime") from exc
    try:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return validate_tenant_expiration(parsed)
    except (OverflowError, ValueError) as exc:
        raise ValueError("expires_at must fit MariaDB DATETIME") from exc


def _tenant_payload(session, tenant):
    admin_phone = session.scalar(
        select(TenantMember.phone)
        .where(
            TenantMember.tenant_id == tenant.id,
            TenantMember.role == "admin",
        )
        .order_by(TenantMember.id)
        .limit(1)
    )
    return {
        "id": tenant.id,
        "name": tenant.name,
        "status": tenant.status,
        "expires_at": _format_datetime(tenant.expires_at),
        "db_name": tenant.db_name,
        "provisioning_status": tenant.provisioning_status,
        "provisioning_error": tenant.provisioning_error,
        "admin_phone": admin_phone,
    }


def _tenant_payload_by_id(tenant_id):
    with _control_store().session() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        return _tenant_payload(session, tenant)


@bp.post("/auth/login")
def login_platform_admin():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _invalid_request("请求体必须是 JSON 对象")
    username = body.get("username")
    password = body.get("password")
    totp_code = body.get("totp")
    if not all(isinstance(value, str) for value in (
        username,
        password,
        totp_code,
    )):
        return _invalid_request("用户名、密码和 TOTP 不能为空")

    store = _control_store()
    if store is None:
        return error(
            "平台认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()

    credentials = None
    admin = None
    with store.session() as session:
        admin = session.scalar(
            select(PlatformAdmin).where(
                PlatformAdmin.username == username
            )
        )
        valid = admin is not None and check_password_hash(
            admin.password_hash,
            password,
        )
        if valid:
            try:
                secret = store.secret_box.decrypt(
                    admin.totp_secret_ciphertext,
                    purpose="platform-totp-secret",
                )
                valid = pyotp.TOTP(secret).verify(
                    totp_code,
                    valid_window=1,
                )
            except Exception:
                valid = False
        if valid:
            credentials = create_auth_session(
                session,
                kind="platform",
                subject_id=admin.id,
            )

    if credentials is None:
        return error(
            "用户名、密码或 TOTP 无效",
            status_code=401,
            code="AUTH_INVALID",
        ).to_flask_response()

    payload, status_code = success(
        data=_admin_payload(admin, credentials.csrf_token)
    ).to_flask_response()
    response = make_response(payload, status_code)
    response.set_cookie(
        "platform_session",
        credentials.raw_token,
        **session_cookie_options(
            "platform",
            secure=current_app.config.get(
                "SESSION_COOKIE_SECURE",
                False,
            ),
        ),
    )
    return response


@bp.get("/auth/me")
def current_platform_admin():
    csrf_token = refresh_csrf_token(
        _control_store(),
        g.auth_session.id,
        request.cookies.get("platform_session"),
    )
    if csrf_token is None:
        return _platform_auth_error()
    return success(
        data=_admin_payload(g.platform_admin, csrf_token)
    ).to_flask_response()


@bp.post("/auth/logout")
def logout_platform_admin():
    revoke_auth_session(_control_store(), g.auth_session.id)
    payload, status_code = success(
        message="已退出登录"
    ).to_flask_response()
    response = make_response(payload, status_code)
    response.delete_cookie(
        "platform_session",
        path="/platform",
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
        httponly=True,
        samesite="Lax",
    )
    return response


@bp.get("/api/tenants")
def list_tenants():
    with _control_store().session() as session:
        tenants = session.scalars(
            select(Tenant).order_by(Tenant.id)
        ).all()
        data = [_tenant_payload(session, tenant) for tenant in tenants]
    return success(data=data).to_flask_response()


@bp.post("/api/tenants")
def create_tenant():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _invalid_request("请求体必须是 JSON 对象")
    try:
        expires_at = _parse_datetime(body.get("expires_at"))
        provisioner = current_app.extensions.get("tenant_provisioner")
        if provisioner is None:
            return error(
                "租户 Provisioner 未配置",
                status_code=500,
                code="CONFIG_INCOMPLETE",
            ).to_flask_response()
        tenant = provisioner.create(
            body.get("name"),
            body.get("admin_phone"),
            expires_at,
        )
    except TenantPhoneConflict:
        return error(
            "该手机号已属于其他租户",
            status_code=409,
            code="PHONE_CONFLICT",
        ).to_flask_response()
    except ValueError:
        return _invalid_request("租户名称、手机号或到期时间无效")

    data = _tenant_payload_by_id(tenant.id)
    if tenant.provisioning_status != "active":
        return error(
            "租户数据库创建失败",
            status_code=503,
            code="PROVISIONING_FAILED",
            data=data,
        ).to_flask_response()
    return success(data=data, status_code=201).to_flask_response()


@bp.post("/api/tenants/<int:tenant_id>/retry")
def retry_tenant(tenant_id):
    provisioner = current_app.extensions.get("tenant_provisioner")
    if provisioner is None:
        return error(
            "租户 Provisioner 未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()
    try:
        tenant = provisioner.retry(tenant_id)
    except TenantNotFound:
        return error(
            "租户不存在",
            status_code=404,
            code="NOT_FOUND",
        ).to_flask_response()

    data = _tenant_payload_by_id(tenant.id)
    if tenant.provisioning_status != "active":
        return error(
            "租户数据库创建失败",
            status_code=503,
            code="PROVISIONING_FAILED",
            data=data,
        ).to_flask_response()
    return success(data=data).to_flask_response()


def _validated_patch(body):
    if not isinstance(body, dict) or not body:
        raise ValueError("patch body is required")
    if not set(body).issubset(_TENANT_PATCH_FIELDS):
        raise ValueError("unsupported patch field")
    if "expires_at" in body and "extend_days" in body:
        raise ValueError("choose direct expiry or extension")

    values = {}
    if "name" in body:
        name = body["name"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 128
        ):
            raise ValueError("tenant name is required")
        values["name"] = name.strip()
    if "admin_phone" in body:
        values["admin_phone"] = normalize_china_phone(
            body["admin_phone"]
        )
    if "status" in body:
        if body["status"] not in {"active", "suspended"}:
            raise ValueError("invalid tenant status")
        values["status"] = body["status"]
    if "expires_at" in body:
        values["expires_at"] = _parse_datetime(body["expires_at"])
    if "extend_days" in body:
        days = body["extend_days"]
        if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
            raise ValueError("extend_days must be a positive integer")
        values["extend_days"] = days
    return values


@bp.patch("/api/tenants/<int:tenant_id>")
def patch_tenant(tenant_id):
    try:
        values = _validated_patch(request.get_json(silent=True))
    except ValueError:
        return _invalid_request("租户修改内容无效")

    store = _control_store()
    phone = values.get("admin_phone")
    lock_names = (
        (f"tenant-phone-{hash_token(phone)[:48]}",)
        if phone is not None
        else ()
    )
    scope = (
        store.locked_session(lock_names, timeout=5)
        if lock_names
        else store.session()
    )
    try:
        with scope as session:
            tenant = session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update()
            )
            if tenant is None:
                return error(
                    "租户不存在",
                    status_code=404,
                    code="NOT_FOUND",
                ).to_flask_response()
            if "name" in values:
                tenant.name = values["name"]
            if "status" in values:
                tenant.status = values["status"]
            if "expires_at" in values:
                tenant.expires_at = values["expires_at"]
            if "extend_days" in values:
                base = max(tenant.expires_at, datetime.utcnow())
                tenant.expires_at = validate_tenant_expiration(
                    base + timedelta(days=values["extend_days"])
                )
            if phone is not None:
                first_admin = session.scalar(
                    select(TenantMember)
                    .where(
                        TenantMember.tenant_id == tenant_id,
                        TenantMember.role == "admin",
                    )
                    .order_by(TenantMember.id)
                    .limit(1)
                )
                conflict = session.scalar(
                    select(TenantMember).where(
                        TenantMember.phone == phone,
                        TenantMember.id != first_admin.id,
                    )
                )
                if conflict is not None:
                    raise TenantPhoneConflict(phone)
                first_admin.phone = phone
    except (TenantPhoneConflict, IntegrityError):
        return error(
            "该手机号已属于其他租户",
            status_code=409,
            code="PHONE_CONFLICT",
        ).to_flask_response()
    except (OverflowError, ValueError):
        return _invalid_request("租户修改内容无效")

    return success(
        data=_tenant_payload_by_id(tenant_id)
    ).to_flask_response()


def register_platform_commands(app):
    app.cli.add_command(bootstrap_platform_admin)
    app.cli.add_command(upgrade_tenant_databases)


@click.command("bootstrap-platform-admin")
@click.option("--username", required=True)
@with_appcontext
def bootstrap_platform_admin(username):
    store = _control_store()
    if store is None:
        raise click.ClickException("Control database is not configured.")
    username = username.strip()
    if not username or len(username) > 64:
        raise click.ClickException("Username is invalid.")

    with store.session() as session:
        if session.scalar(select(func.count(PlatformAdmin.id))):
            raise click.ClickException(
                "The first platform administrator already exists."
            )

    password = click.prompt(
        "Password",
        hide_input=True,
        confirmation_prompt=True,
    )
    totp_secret = click.prompt("TOTP secret", hide_input=True).strip()
    try:
        pyotp.TOTP(totp_secret).now()
    except Exception as exc:
        raise click.ClickException("TOTP secret is invalid.") from exc
    encrypted_secret = store.secret_box.encrypt(
        totp_secret,
        purpose="platform-totp-secret",
    )

    try:
        with store.locked_session(
            ("bootstrap-platform-admin",),
            timeout=5,
        ) as session:
            if session.scalar(select(func.count(PlatformAdmin.id))):
                raise click.ClickException(
                    "The first platform administrator already exists."
                )
            session.add(
                PlatformAdmin(
                    username=username,
                    password_hash=generate_password_hash(password),
                    totp_secret_ciphertext=encrypted_secret,
                )
            )
    except (IntegrityError, TimeoutError) as exc:
        raise click.ClickException(
            "Unable to create the first platform administrator."
        ) from exc
    click.echo("Platform administrator created.")


@click.command("upgrade-tenant-databases")
@click.pass_context
@with_appcontext
def upgrade_tenant_databases(ctx):
    store = _control_store()
    provisioner = current_app.extensions.get("tenant_provisioner")
    if store is None or provisioner is None:
        raise click.ClickException("Tenant Provisioner is not configured.")

    with store.session() as session:
        tenants = session.scalars(
            select(Tenant)
            .where(Tenant.provisioning_status == "active")
            .order_by(Tenant.id)
        ).all()
    head = business_migration_head(provisioner.migrations_directory)
    failed = False
    for tenant in tenants:
        try:
            provisioner.upgrade(tenant)
            succeeded = True
        except Exception as exc:
            succeeded = False
            failed = True
            current_app.logger.error(
                "Tenant database upgrade failed tenant_id=%s type=%s",
                tenant.id,
                type(exc).__name__,
            )
        click.echo(
            json.dumps(
                {
                    "tenant_id": tenant.id,
                    "db_name": tenant.db_name,
                    "head": head,
                    "success": succeeded,
                },
                sort_keys=True,
            )
        )
    if failed:
        ctx.exit(1)
